"""Canonical, deterministic research backtest over a validated snapshot.

No network calls or hidden source fallbacks occur here. Financial conventions and
limitations are versioned in docs/model.md and engine-spec.json.
"""

from __future__ import annotations

import calendar
import math
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, time
from statistics import mean, stdev
from typing import Any, Literal
from zoneinfo import ZoneInfo

import exchange_calendars
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.data import DataError, Dataset

MODEL_VERSION = "5.0.0-legacy-unvalidated"
SECTORS = ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY")
MACRO = ("DGS2", "DGS10", "DFII10", "T10YIE", "VIXCLS", "BAMLH0A0HYM2", "DFF")
MODES = ("extreme1", "ranked3", "longonly3")
NEW_YORK = ZoneInfo("America/New_York")
# rates, inflation, volatility, credit, legacy "value" coefficient (not valuation data).
EXPOSURES = {
	"XLB": (-0.1, 0.8, -0.2, -0.1, 0.4),
	"XLC": (-0.4, 0, -0.2, 0, -0.3),
	"XLE": (0.1, 1, -0.1, 0, 0.8),
	"XLF": (0.8, 0.2, -0.1, -0.5, 0.8),
	"XLI": (0.1, 0.5, -0.2, -0.2, 0.4),
	"XLK": (-1, -0.2, -0.4, 0, -1),
	"XLP": (-0.3, 0.1, 0.7, 0.2, 0.2),
	"XLRE": (-1, 0.2, -0.3, -0.8, 0.1),
	"XLU": (-1, 0, 0.5, -0.2, 0.2),
	"XLV": (-0.2, 0, 0.7, 0.2, 0.2),
	"XLY": (-0.6, -0.2, -0.5, -0.4, -0.4),
}
ASSUMPTIONS = [
	"Unvalidated legacy research score; not a calibrated probability or investment recommendation.",
	"Month-end decisions at 23:59:59 America/New_York; execution at the next session close.",
	"Targets reference pre-trade NAV; one-way fees apply to absolute signed traded notional.",
	"Entry and final liquidation are charged. Benchmark is a frictionless USD total-return index.",
	"Extra long notional above equity is financed at available DFF, ACT/365; no cash or collateral rebate.",
	"Short borrow accrues on prior-close marked short notional, ACT/365; short total returns include dividends.",
	"Daily close insolvency terminates at zero; intraday margin calls and executable fills are not modeled.",
	"Sharpe uses completed monthly cycle excess returns and sqrt(12); drawdown is sampled monthly.",
]


class BacktestParams(BaseModel):
	"""Validated public parameters; unknown inputs and non-finite costs are errors."""

	model_config = ConfigDict(extra="forbid", frozen=True)
	start: date
	end: date | None = None
	mode: Literal["extreme1", "ranked3", "longonly3", "compare"] = "extreme1"
	cost_bps: float = Field(default=10, ge=0, le=1000, strict=True, allow_inf_nan=False)
	short_borrow_bps: float = Field(default=50, ge=0, le=10000, strict=True, allow_inf_nan=False)
	rebalance: Literal["monthly"] = "monthly"

	@field_validator("start", "end", mode="before")
	@classmethod
	def validate_date(cls, value: object) -> date | None:
		"""Accept exact ISO dates or date objects, never timestamps or coercions."""
		if value is None:
			return None
		if type(value) is date:
			return value
		if isinstance(value, str) and len(value) == 10:
			parsed = date.fromisoformat(value)
			if parsed.isoformat() == value:
				return parsed
		raise ValueError("Use an exact YYYY-MM-DD calendar date")

	@model_validator(mode="after")
	def validate_period(self) -> BacktestParams:
		"""Bound the supported full-universe evaluation period."""
		today = datetime.now(UTC).date()
		if self.start > today or (self.end is not None and self.end > today):
			raise ValueError("Backtest dates cannot be in the future")
		if self.start < date(2018, 6, 19):
			raise ValueError("The full eleven-sector universe starts 2018-06-19")
		if self.end is not None and self.end <= self.start:
			raise ValueError("end must be later than start")
		return self


def _cutoff(day: date, hour: int = 23) -> datetime:
	return datetime.combine(day, time(hour, 59, 59) if hour == 23 else time(hour), NEW_YORK)


def _month_end(day: date) -> date:
	return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def _month_number(day: date) -> int:
	return day.year * 12 + day.month


class _History:
	def __init__(self, dataset: Dataset) -> None:
		self.series: dict[str, dict[date, list[Any]]] = {}
		self.dates: dict[str, list[date]] = {}
		for name, series in dataset.series.items():
			grouped: dict[date, list[Any]] = defaultdict(list)
			for observation in series.observations:
				grouped[observation.date].append(observation)
			self.series[name] = dict(grouped)
			self.dates[name] = sorted(grouped)

	def exact(self, name: str, day: date, cutoff: datetime) -> float:
		versions = self.series.get(name, {}).get(day, [])
		eligible = [item for item in versions if item.available_at <= cutoff]
		if not eligible:
			raise DataError(
				"missing_history",
				"A required price is missing or was unavailable at its cutoff.",
				{"series": name, "date": str(day), "cutoff": cutoff.isoformat()},
			)
		return max(eligible, key=lambda item: item.available_at).value

	def latest(self, name: str, cutoff: datetime, max_age: int = 10) -> float:
		dates = self.dates.get(name, [])
		index = bisect_right(dates, cutoff.date()) - 1
		for day in reversed(dates[: index + 1]):
			if (cutoff.date() - day).days > max_age:
				break
			eligible = [item for item in self.series[name][day] if item.available_at <= cutoff]
			if eligible:
				return max(eligible, key=lambda item: item.available_at).value
		raise DataError(
			"missing_macro_history",
			"A required macro observation is missing, stale or unavailable.",
			{"series": name, "cutoff": cutoff.isoformat(), "maximum_age_days": max_age},
		)


def score_sectors(state: dict[str, float], momentum: dict[str, float]) -> list[dict]:
	"""Apply the preserved legacy formula, with deterministic alphabetical ties.

	Args:
		state: Normalized rates, curve, inflation, vol and credit states in [-1, 1].
		momentum: Six-month total returns indexed by sector ETF.

	Returns:
		Descending score records. Scores are unbounded research ranks, not probabilities.
	"""
	scores = []
	for symbol in SECTORS:
		rates, inflation, volatility, credit, value = EXPOSURES[symbol]
		macro_score = (
			-state["rates"] * rates * 18
			+ state["curve"] * rates * 12
			+ state["inflation"] * inflation * 14
			- state["vol"] * volatility * 10
			- state["credit"] * credit * 12
			+ value * (state["rates"] * 0.25 + state["inflation"] * 0.25) * 8
		)
		momentum_score = max(-1, min(1, momentum[symbol] / 0.20)) * 22
		scores.append({"symbol": symbol, "score": 50 + macro_score + momentum_score})
	return sorted(scores, key=lambda row: (-row["score"], row["symbol"]))


def target_weights(mode: str, ranked_symbols: list[str]) -> dict[str, float]:
	"""Map conviction ranks to signed target weights, with the worst short first.

	Args:
		mode: A concrete supported strategy, not compare.
		ranked_symbols: All eleven unique sector symbols in best-to-worst order.

	Returns:
		Signed target notionals per unit of pre-trade NAV.

	Raises:
		ValueError: When the strategy or ranked universe is invalid.
	"""
	if len(ranked_symbols) != len(SECTORS) or set(ranked_symbols) != set(SECTORS):
		raise ValueError("Rankings must contain every sector exactly once")
	if mode == "extreme1":
		return {ranked_symbols[0]: 2.0, ranked_symbols[-1]: -2.0}
	if mode == "longonly3":
		return dict(zip(ranked_symbols[:3], (1.0, 0.65, 0.45), strict=True))
	if mode == "ranked3":
		weights = dict(zip(ranked_symbols[:3], (0.5, 0.25, 0.25), strict=True))
		weights.update(zip(reversed(ranked_symbols[-3:]), (-0.5, -0.25, -0.25), strict=True))
		return weights
	raise ValueError("A concrete strategy mode is required")


def _macro_snapshot(history: _History, decision: date) -> dict[str, float]:
	values = {name: history.latest(name, _cutoff(decision)) for name in MACRO[:-1]}
	return {
		"rates": values["DFII10"],
		"curve": values["DGS10"] - values["DGS2"],
		"inflation": values["T10YIE"],
		"vol": values["VIXCLS"],
		"credit": values["BAMLH0A0HYM2"],
	}


def _prepare(dataset: Dataset, params: BacktestParams) -> dict:
	required = [f"{symbol}_TR" for symbol in (*SECTORS, "SPY")]
	missing = sorted(set(required + list(MACRO)) - set(dataset.series))
	if missing:
		raise DataError(
			"missing_series", "The backtest requires complete input series.", {"series": missing}
		)
	bases = {dataset.series[name].price_basis for name in required}
	if len(bases) != 1 or not bases <= {"total_return_net", "total_return_gross"}:
		raise DataError(
			"return_basis_mismatch", "All ETF return indices must share one dividend convention."
		)
	for name in required:
		series = dataset.series[name]
		if series.currency != "USD" or series.unit != "index":
			raise DataError(
				"invalid_price_unit",
				"Backtests require USD total-return indices.",
				{"series": name},
			)
	for name in MACRO:
		series = dataset.series[name]
		basis, unit = ("index", "index") if name == "VIXCLS" else ("rate", "percent")
		if series.price_basis != basis or series.unit != unit:
			raise DataError(
				"invalid_macro_unit",
				"A macro series has an incompatible unit or basis.",
				{"series": name},
			)
	history = _History(dataset)
	sessions = [day for day in dataset.calendar if day <= dataset.as_of]
	end = min(params.end or dataset.as_of, dataset.as_of)
	month_sessions: dict[int, list[date]] = defaultdict(list)
	for day in sessions:
		month_sessions[_month_number(day)].append(day)
	months = sorted(month_sessions)
	if any(right != left + 1 for left, right in zip(months, months[1:])):
		raise DataError("calendar_gap", "The session calendar contains nonconsecutive months.")
	boundaries = []
	for index, month in enumerate(months[:-1]):
		decision = _month_end(month_sessions[month][-1])
		execution = month_sessions[months[index + 1]][0]
		if decision < execution <= end and execution >= params.start:
			boundaries.append((month, decision, execution))
	if len(boundaries) < 2:
		raise DataError(
			"insufficient_periods", "No complete monthly execution-to-execution cycle is available."
		)
	first_month = boundaries[0][0]
	if first_month - 12 < months[0]:
		raise DataError(
			"insufficient_warmup",
			"Twelve pre-decision months of macro history are required; evaluation was not shifted.",
			{
				"first_decision": str(boundaries[0][1]),
				"minimum_months": 12,
			},
		)
	warmup_first = first_month - 12
	# Mandatory consecutive history and evaluated decisions never permit gaps.
	# Older optional normalization history can only extend the contiguous window.
	# Each snapshot stays frozen at its own cutoff: later revisions never rewrite it.
	macro_history = {
		month: _macro_snapshot(history, _month_end(month_sessions[month][-1]))
		for month in months
		if warmup_first <= month <= boundaries[-2][0]
	}
	for month in range(warmup_first - 1, max(months[0], first_month - 60) - 1, -1):
		try:
			macro_history[month] = _macro_snapshot(history, _month_end(month_sessions[month][-1]))
		except DataError as exc:
			if exc.code != "missing_macro_history":
				raise
			break
		warmup_first = month
	price_start = month_sessions[first_month - 6][-1]
	price_sessions = [day for day in sessions if price_start <= day <= boundaries[-1][2]]
	prices = {
		symbol: {day: history.exact(f"{symbol}_TR", day, _cutoff(day)) for day in price_sessions}
		for symbol in (*SECTORS, "SPY")
	}
	decisions = []
	for month, decision, execution in boundaries[:-1]:
		historical_months = range(max(warmup_first, month - 60), month)
		state = {}
		for factor in ("rates", "curve", "inflation", "vol", "credit"):
			values = [macro_history[past][factor] for past in historical_months]
			deviation = stdev(values)
			state[factor] = (
				max(-1, min(1, (macro_history[month][factor] - mean(values)) / deviation / 2))
				if deviation
				else 0.0
			)
		current_day, past_day = month_sessions[month][-1], month_sessions[month - 6][-1]
		momentum = {
			symbol: history.exact(f"{symbol}_TR", current_day, _cutoff(decision))
			/ history.exact(f"{symbol}_TR", past_day, _cutoff(decision))
			- 1
			for symbol in SECTORS
		}
		decisions.append(
			{
				"decision": decision,
				"execution": execution,
				"state": state,
				"scores": score_sectors(state, momentum),
			}
		)
	exchange = exchange_calendars.get_calendar(
		"XNYS", start=boundaries[0][2].isoformat(), end=boundaries[-1][2].isoformat()
	)
	funding = {
		day: history.latest("DFF", exchange.session_close(day.isoformat()).to_pydatetime()) / 100
		for day in sessions
		if boundaries[0][2] <= day < boundaries[-1][2]
	}
	return {
		"decisions": decisions,
		"boundaries": boundaries,
		"sessions": sessions,
		"prices": prices,
		"funding": funding,
		"return_basis": next(iter(bases)),
		"period": {
			"requested_start": str(params.start),
			"requested_end": str(params.end) if params.end else None,
			"warmup_start": str(_month_end(month_sessions[warmup_first][-1])),
			"initial_normalization_months": first_month - warmup_first,
			"first_decision": str(boundaries[0][1]),
			"first_execution": str(boundaries[0][2]),
			"first_return": str(boundaries[1][2]),
			"last_complete_return": str(boundaries[-1][2]),
			"complete_periods": len(decisions),
			"excluded_partial": boundaries[-1][2] < end,
			"available_through": str(dataset.as_of),
		},
	}


def performance_statistics(
	returns: list[float],
	cash_returns: list[float],
	benchmark_returns: list[float],
	equity: list[float],
	elapsed_days: int,
	turnover: float,
	*,
	ruined: bool = False,
) -> dict:
	"""Calculate statistics from complete consecutive monthly cycles.

	Args:
		returns: Net strategy returns, including fees and financing.
		cash_returns: ACT/365 compounded reference cash returns over the same cycles.
		benchmark_returns: Benchmark returns over precisely the same cycles.
		equity: Monthly sampled NAV, including its initial 100 and any terminal zero.
		elapsed_days: Actual calendar duration from first execution to valuation.
		turnover: Total one-way absolute traded notional divided by pre-trade NAV.
		ruined: Whether a daily close insolvency interrupted the final cycle.

	Returns:
		Finite metrics or null with a reason in metric_status.

	Raises:
		ValueError: If aligned return vectors, duration or finite inputs are invalid.
	"""
	if not (len(returns) == len(cash_returns) == len(benchmark_returns)) or elapsed_days <= 0:
		raise ValueError("Statistics require aligned returns and positive elapsed time")
	if (
		len(equity) < 2
		or equity[0] <= 0
		or any(value < 0 for value in equity)
		or any(
			not math.isfinite(value)
			for value in (*returns, *cash_returns, *benchmark_returns, *equity)
		)
	):
		raise ValueError("Statistics require finite financial values and an equity path")
	years = elapsed_days / 365.25
	excess = [value - reference for value, reference in zip(returns, cash_returns, strict=True)]
	metric_status = {}
	volatility = stdev(returns) * math.sqrt(12) if len(returns) >= 2 else None
	deviation = stdev(excess) if len(excess) >= 2 else 0
	sharpe = mean(excess) / deviation * math.sqrt(12) if deviation else None
	if volatility is None:
		metric_status["annualized_volatility"] = "insufficient_completed_periods"
	if sharpe is None:
		metric_status["sharpe"] = (
			"zero_excess_return_variance" if len(excess) >= 2 else "insufficient_completed_periods"
		)
	try:
		cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if equity[-1] > 0 else None
	except OverflowError:
		cagr = None
		metric_status["cagr"] = "annualization_numeric_overflow"
	if cagr is None:
		metric_status.setdefault("cagr", "nonpositive_terminal_equity")
	if not returns:
		metric_status["hit_rate"] = "insufficient_completed_periods"
	if ruined:
		cagr, sharpe, volatility = None, None, None
		for key in ("cagr", "sharpe", "annualized_volatility"):
			metric_status[key] = "terminal_insolvency"
	peak, drawdown = equity[0], 0.0
	for nav in equity:
		peak = max(peak, nav)
		drawdown = min(drawdown, nav / peak - 1)
	return {
		"total_return": equity[-1] / equity[0] - 1,
		"cagr": cagr,
		"annualized_volatility": volatility,
		"sharpe": sharpe,
		"max_drawdown_monthly": drawdown,
		"hit_rate": mean(
			[value > reference for value, reference in zip(returns, benchmark_returns, strict=True)]
		)
		if returns
		else None,
		"annualized_turnover": turnover / years,
		"periods": len(returns),
		"benchmark_total_return": math.prod(1 + value for value in benchmark_returns) - 1,
		"metric_status": metric_status,
	}


def _simulate(prepared: dict, params: BacktestParams, mode: str) -> dict:
	prices, sessions = prepared["prices"], prepared["sessions"]
	cash, nav, benchmark = 100.0, 100.0, 100.0
	positions: dict[str, float] = {}
	curve = [{"date": prepared["period"]["first_execution"], "strategy": 100.0, "benchmark": 100.0}]
	holdings, completed_returns, cash_returns, benchmark_returns = [], [], [], []
	total_turnover, ruined = 0.0, False
	terminal_date = None
	for index, decision in enumerate(prepared["decisions"]):
		start = decision["execution"]
		end = prepared["boundaries"][index + 1][2]
		period_start_nav = nav
		weights = target_weights(mode, [row["symbol"] for row in decision["scores"]])
		pretrade_weights = {symbol: value / nav for symbol, value in positions.items()}
		targets = {symbol: weight * nav for symbol, weight in weights.items()}
		traded = sum(
			abs(targets.get(symbol, 0) - positions.get(symbol, 0))
			for symbol in set(targets) | set(positions)
		)
		turnover = traded / nav
		trading_cost = traded * params.cost_bps / 10000
		cash -= sum(targets.values()) - sum(positions.values()) + trading_cost
		positions = targets
		nav = cash + sum(positions.values())
		long_notional = sum(max(value, 0) for value in positions.values())
		debt = max(long_notional - period_start_nav, 0)
		funding_cost, borrow_cost, cash_growth = 0.0, 0.0, 1.0
		long_pnl, short_pnl, liquidation_cost, liquidation_turnover = 0.0, 0.0, 0.0, 0.0
		period_sessions = [day for day in sessions if start <= day <= end]
		last_day = start
		if nav <= 0:
			ruined, terminal_date, nav = True, str(start), 0.0
		for previous, current in zip(period_sessions, period_sessions[1:]):
			if ruined:
				break
			fraction = (current - previous).days / 365
			rate = prepared["funding"][previous]
			funding = debt * rate * fraction
			borrow = (
				-sum(min(value, 0) for value in positions.values())
				* params.short_borrow_bps
				/ 10000
				* fraction
			)
			funding_cost += funding
			borrow_cost += borrow
			cash -= funding + borrow
			cash_growth *= 1 + rate * fraction
			for symbol, value in list(positions.items()):
				pnl = value * (prices[symbol][current] / prices[symbol][previous] - 1)
				if value >= 0:
					long_pnl += pnl
				else:
					short_pnl += pnl
				positions[symbol] += pnl
			nav = cash + sum(positions.values())
			benchmark *= prices["SPY"][current] / prices["SPY"][previous]
			last_day = current
			if not math.isfinite(nav) or not math.isfinite(benchmark):
				raise DataError(
					"nonfinite_calculation", "Portfolio arithmetic exceeded finite numeric limits."
				)
			if nav <= 0:
				ruined, terminal_date, nav = True, str(current), 0.0
				break
		if not ruined and index == len(prepared["decisions"]) - 1:
			liquidation_notional = sum(abs(value) for value in positions.values())
			liquidation_turnover = liquidation_notional / nav
			liquidation_cost = liquidation_notional * params.cost_bps / 10000
			nav -= liquidation_cost
			cash, positions = nav, {}
			if nav <= 0:
				ruined, terminal_date, nav = True, str(end), 0.0
		trading_cost += liquidation_cost
		total_turnover += turnover + liquidation_turnover
		period_return = nav / period_start_nav - 1
		benchmark_return = prices["SPY"][last_day] / prices["SPY"][start] - 1
		complete = last_day == end and not ruined
		if complete:
			completed_returns.append(period_return)
			cash_returns.append(cash_growth - 1)
			benchmark_returns.append(benchmark_return)
		curve.append({"date": str(last_day), "strategy": nav, "benchmark": benchmark})
		holdings.append(
			{
				"decision_date": str(decision["decision"]),
				"execution_date": str(start),
				"end_date": str(last_day),
				"weights": weights,
				"pretrade_weights": pretrade_weights,
				"turnover": turnover,
				"liquidation_turnover": liquidation_turnover,
				"trading_cost": trading_cost / period_start_nav,
				"liquidation_cost": liquidation_cost / period_start_nav,
				"funding_cost": funding_cost / period_start_nav,
				"borrow_cost": borrow_cost / period_start_nav,
				"period_return": period_return,
				"benchmark_return": benchmark_return,
				"cash_return": cash_growth - 1,
				"long_contribution": long_pnl / period_start_nav,
				"short_contribution": short_pnl / period_start_nav,
				"scores": decision["scores"],
				"state": decision["state"],
				"complete": complete,
			}
		)
		if ruined:
			break
	elapsed = (date.fromisoformat(curve[-1]["date"]) - date.fromisoformat(curve[0]["date"])).days
	# A fee-only entry insolvency has no elapsed period; avoid invented annualized metrics.
	stats = performance_statistics(
		completed_returns,
		cash_returns,
		benchmark_returns,
		[row["strategy"] for row in curve],
		max(elapsed, 1),
		total_turnover,
		ruined=ruined,
	)
	stats["benchmark_total_return"] = curve[-1]["benchmark"] / 100 - 1
	if ruined:
		stats["hit_rate"] = None
		stats["metric_status"]["hit_rate"] = "terminal_insolvency"
	if elapsed == 0:
		stats["annualized_turnover"] = None
		stats["metric_status"]["annualized_turnover"] = "zero_elapsed_time"
	long_gross, short_gross = {"extreme1": (2, 2), "ranked3": (1, 1), "longonly3": (2.1, 0)}[mode]
	return {
		"strategy": {
			"id": mode,
			"label": {
				"extreme1": "Extreme +200% / -200%",
				"ranked3": "Ranked three +100% / -100%",
				"longonly3": "Long only 100% / 65% / 45%",
			}[mode],
			"weights": {
				"extreme1": [2, -2],
				"ranked3": [0.5, 0.25, 0.25, -0.5, -0.25, -0.25],
				"longonly3": [1, 0.65, 0.45],
			}[mode],
			"long_gross": long_gross,
			"short_gross": short_gross,
			"net": long_gross - short_gross,
			"gross": long_gross + short_gross,
		},
		"status": "ruined" if ruined else "complete",
		"terminal_date": terminal_date,
		"stats": stats,
		"equity_curve": curve,
		"holdings": holdings,
		"diagnostics": {
			"observed_periods": len(holdings),
			"complete_periods": len(completed_returns),
			"average_long_contribution": mean(row["long_contribution"] for row in holdings),
			"average_short_contribution": mean(row["short_contribution"] for row in holdings),
			"total_trading_cost_fraction_sum": sum(row["trading_cost"] for row in holdings),
			"total_funding_cost_fraction_sum": sum(row["funding_cost"] for row in holdings),
			"total_borrow_cost_fraction_sum": sum(row["borrow_cost"] for row in holdings),
			"drawdown_sampling": "monthly cycle endpoints plus terminal insolvency",
			"return_basis": prepared["return_basis"],
			"validation": "unvalidated_legacy_research",
		},
		"assumptions": ASSUMPTIONS.copy(),
	}


def _validate_finite_result(value: object) -> None:
	if isinstance(value, float) and not math.isfinite(value):
		raise DataError("nonfinite_calculation", "A result contains a non-finite financial value.")
	if isinstance(value, dict):
		for item in value.values():
			_validate_finite_result(item)
	elif isinstance(value, list):
		for item in value:
			_validate_finite_result(item)


def run_backtest(dataset: Dataset, params: BacktestParams) -> dict:
	"""Run requested strategies on one validated point-in-time snapshot.

	Args:
		dataset: Immutable shared data_mesh snapshot with availability metadata.
		params: Validated evaluation period and financial assumptions.

	Returns:
		A finite JSON-ready response with concrete strategy identities and source lineage.

	Raises:
		DataError: If coverage, units, timing, warm-up or financial invariants fail.
	"""
	prepared = _prepare(dataset, params)
	modes = MODES if params.mode == "compare" else (params.mode,)
	response = {
		"ok": True,
		"dataset_id": dataset.dataset_id,
		"model_version": MODEL_VERSION,
		"params": params.model_dump(mode="json"),
		"period": prepared["period"],
		"results": {mode: _simulate(prepared, params, mode) for mode in modes},
	}
	_validate_finite_result(response)
	return response
