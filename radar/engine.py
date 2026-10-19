"""Canonical, deterministic research backtest over a validated snapshot.

No network calls or hidden source fallbacks occur here. Financial conventions and
limitations are versioned in docs/model.md and engine-spec.json.
"""

from __future__ import annotations

import calendar
import math
from bisect import bisect_right
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from statistics import mean, stdev
from typing import Any, Literal
from zoneinfo import ZoneInfo

import exchange_calendars
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radar.data import DataError, Dataset

MODEL_VERSION = "5.1.0-legacy-unvalidated"
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
	"Scheduled calendar-end decisions at 23:59:59 America/New_York; next-session close execution.",
	"Targets reference pre-trade NAV; one-way fees apply to absolute signed traded notional.",
	"Entry and final liquidation are charged. Benchmark is a frictionless USD total-return index.",
	"Extra long notional above equity is financed at available DFF, ACT/365; no cash or collateral rebate.",
	"Short borrow accrues on prior-close marked short notional, ACT/365; short total returns include dividends.",
	"Daily close insolvency terminates at zero; intraday margin calls and executable fills are not modeled.",
	"Sharpe uses completed cycle excess returns and sqrt(52/12/4) for weekly/monthly/quarterly cycles.",
	"Calendar-year returns and daily drawdowns use marked NAV; incomplete years are explicitly labelled.",
]


class BacktestParams(BaseModel):
	"""Validated public parameters; unknown inputs and non-finite costs are errors."""

	model_config = ConfigDict(extra="forbid", frozen=True)
	start: date
	end: date | None = None
	mode: Literal["extreme1", "ranked3", "longonly3", "compare"] = "extreme1"
	cost_bps: float = Field(default=10, ge=0, le=1000, strict=True, allow_inf_nan=False)
	short_borrow_bps: float = Field(default=50, ge=0, le=10000, strict=True, allow_inf_nan=False)
	rebalance: Literal["weekly", "monthly", "quarterly"] = "monthly"
	top_n: int = Field(default=3, ge=1, le=5, strict=True)

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
		for position in range(index, -1, -1):
			day = dates[position]
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


def sector_score_components(state: dict[str, float], momentum: float, symbol: str) -> dict:
	"""Return additive research-score points, never realized return attribution."""
	rates, inflation, volatility, credit, value = EXPOSURES[symbol]
	return {
		"rates": -state["rates"] * rates * 18,
		"curve": state["curve"] * rates * 12,
		"inflation": state["inflation"] * inflation * 14,
		"volatility": -state["vol"] * volatility * 10,
		"credit": -state["credit"] * credit * 12,
		"legacy_value": value * (state["rates"] * 0.25 + state["inflation"] * 0.25) * 8,
		"momentum": max(-1, min(1, momentum / 0.20)) * 22,
	}


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
		components = sector_score_components(state, momentum[symbol], symbol)
		scores.append({"symbol": symbol, "score": 50 + sum(components.values())})
	return sorted(scores, key=lambda row: (-row["score"], row["symbol"]))


def target_weights(mode: str, ranked_symbols: list[str], top_n: int = 3) -> dict[str, float]:
	"""Map conviction ranks to signed target weights, with the worst short first.

	Args:
		mode: A concrete supported strategy, not compare.
		ranked_symbols: All eleven unique sector symbols in best-to-worst order.
		top_n: Ranked-basket size, ignored by the two fixed-exposure strategies.

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
		if type(top_n) is not int or not 1 <= top_n <= 5:
			raise ValueError("Ranked basket size must be an integer between one and five")
		ranks = [1.0] if top_n == 1 else [0.5] + [0.5 / (top_n - 1)] * (top_n - 1)
		weights = dict(zip(ranked_symbols[:top_n], ranks, strict=True))
		weights.update(zip(reversed(ranked_symbols[-top_n:]), (-w for w in ranks), strict=True))
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


def _prepare(dataset: Dataset, params: BacktestParams, history: _History | None = None) -> dict:
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
	history = history or _History(dataset)
	sessions = [day for day in dataset.calendar if day <= dataset.as_of]
	end = min(params.end or dataset.as_of, dataset.as_of)
	month_sessions: dict[int, list[date]] = defaultdict(list)
	for day in sessions:
		month_sessions[_month_number(day)].append(day)
	months = sorted(month_sessions)
	if any(right != left + 1 for left, right in zip(months, months[1:])):
		raise DataError("calendar_gap", "The session calendar contains nonconsecutive months.")
	if params.rebalance == "weekly":
		anchors = sorted({day + timedelta(days=4 - day.weekday()) for day in sessions})
	else:
		anchors = [
			_month_end(month_sessions[month][-1])
			for month in months
			if params.rebalance == "monthly" or month_sessions[month][-1].month % 3 == 0
		]
	boundaries = []
	for decision in anchors:
		index = bisect_right(sessions, decision)
		if index < len(sessions):
			execution = sessions[index]
			if params.start <= execution <= end:
				boundaries.append((_month_number(decision), decision, execution))
	if len(boundaries) < 2:
		raise DataError(
			"insufficient_periods", "No complete execution-to-execution cycle is available."
		)
	first_month = boundaries[0][0]
	if first_month - 12 < months[0]:
		raise DataError(
			"insufficient_warmup",
			"Twelve pre-decision months of macro history are required; evaluation was not shifted.",
			{"first_decision": str(boundaries[0][1]), "minimum_months": 12},
		)
	warmup_first = first_month - 12
	# Historical training snapshots are frozen at their own month-end cutoffs.
	# Weekly signals use current available inputs, trained only on completed prior months.
	macro_history = {
		month: _macro_snapshot(history, _month_end(month_sessions[month][-1]))
		for month in months
		if warmup_first <= month < boundaries[-2][0]
	}
	for month in range(warmup_first - 1, max(months[0], first_month - 60) - 1, -1):
		try:
			macro_history[month] = _macro_snapshot(history, _month_end(month_sessions[month][-1]))
		except DataError as exc:
			if exc.code != "missing_macro_history":
				raise
			break
		warmup_first = month

	def momentum_days(decision: date) -> tuple[date, date]:
		current_day = sessions[bisect_right(sessions, decision) - 1]
		month = _month_number(decision) - 6
		if params.rebalance != "weekly":
			return current_day, month_sessions[month][-1]
		year, zero_month = divmod(month - 1, 12)
		past_date = date(
			year, zero_month + 1, min(decision.day, calendar.monthrange(year, zero_month + 1)[1])
		)
		return current_day, sessions[bisect_right(sessions, past_date) - 1]

	price_start = momentum_days(boundaries[0][1])[1]
	price_sessions = [day for day in sessions if price_start <= day <= boundaries[-1][2]]
	prices = {
		symbol: {day: history.exact(f"{symbol}_TR", day, _cutoff(day)) for day in price_sessions}
		for symbol in (*SECTORS, "SPY")
	}
	decisions = []
	for month, decision, execution in boundaries[:-1]:
		historical_months = range(max(warmup_first, month - 60), month)
		current_macro = _macro_snapshot(history, decision)
		state = {}
		for factor in ("rates", "curve", "inflation", "vol", "credit"):
			values = [macro_history[past][factor] for past in historical_months]
			deviation = stdev(values)
			state[factor] = (
				max(-1, min(1, (current_macro[factor] - mean(values)) / deviation / 2))
				if deviation
				else 0.0
			)
		current_day, past_day = momentum_days(decision)
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
				"momentum": momentum,
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
		"calendar": list(dataset.calendar),
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
			"rebalance": params.rebalance,
			"periods_per_year": {"weekly": 52, "monthly": 12, "quarterly": 4}[params.rebalance],
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
	periods_per_year: int = 12,
) -> dict:
	"""Calculate statistics from complete consecutive selected-frequency cycles.

	Args:
		returns: Net strategy returns, including fees and financing.
		cash_returns: ACT/365 compounded reference cash returns over the same cycles.
		benchmark_returns: Benchmark returns over precisely the same cycles.
		equity: Cycle-end NAV, including its initial 100 and any terminal zero.
		elapsed_days: Actual calendar duration from first execution to valuation.
		turnover: Total one-way absolute traded notional divided by pre-trade NAV.
		ruined: Whether a daily close insolvency interrupted the final cycle.
		periods_per_year: Conventional frequency scaling: weekly52, monthly12, quarterly4.

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
	if periods_per_year not in (4, 12, 52):
		raise ValueError("Statistics require a supported observation frequency")
	volatility = stdev(returns) * math.sqrt(periods_per_year) if len(returns) >= 2 else None
	deviation = stdev(excess) if len(excess) >= 2 else 0
	sharpe = mean(excess) / deviation * math.sqrt(periods_per_year) if deviation else None
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
		"periods_per_year": periods_per_year,
		"return_frequency": {4: "quarterly", 12: "monthly", 52: "weekly"}[periods_per_year],
		"benchmark_total_return": math.prod(1 + value for value in benchmark_returns) - 1,
		"metric_status": metric_status,
	}


def classify_regime(state: dict[str, float]) -> str:
	"""Classify decision-time factors using documented, uncalibrated research rules."""
	if max(state["vol"], state["credit"]) >= 0.5:
		return "stress"
	if state["inflation"] >= 0.5:
		return "inflation"
	if state["vol"] < 0 and state["credit"] < 0:
		return "low_stress"
	return "balanced"


def _daily_research(daily: list[dict], sessions: list[date]) -> dict:
	"""Derive actual calendar returns and drawdowns from consecutive daily marks."""
	peaks = {"strategy": 100.0, "benchmark": 100.0}
	drawdowns, annual, rolling = [], [], []
	by_year: dict[int, list[dict]] = defaultdict(list)
	dates = [date.fromisoformat(row["date"]) for row in daily]
	for row, day in zip(daily, dates, strict=True):
		point = {"date": row["date"]}
		for key in peaks:
			peaks[key] = max(peaks[key], row[key])
			point[key] = row[key] / peaks[key] - 1
		drawdowns.append(point)
		by_year[day.year].append(row)
		previous_year = (
			day.replace(year=day.year - 1, day=min(day.day, 28))
			if day.month == 2 and day.day == 29
			else day.replace(year=day.year - 1)
		)
		index = bisect_right(dates, previous_year) - 1
		if index >= 0 and daily[index]["strategy"] > 0:
			rolling.append(
				{
					"date": row["date"],
					"value": row["strategy"] / daily[index]["strategy"]
					- row["benchmark"] / daily[index]["benchmark"],
				}
			)
	previous = {"strategy": 100.0, "benchmark": 100.0}
	for year, rows in by_year.items():
		end = rows[-1]
		values = {
			key: end[key] / previous[key] - 1 if previous[key] > 0 else None for key in previous
		}
		year_sessions = [day for day in sessions if day.year == year]
		# A complete return year needs an initial mark before its first session and its last session.
		partial = (
			dates[0].year == year
			or date.fromisoformat(end["date"]) < year_sessions[-1]
			or year_sessions[-1].month < 12
		)
		annual.append(
			{
				"year": year,
				**values,
				"excess": values["strategy"] - values["benchmark"]
				if values["strategy"] is not None
				else None,
				"partial": partial,
				"start": rows[0]["date"],
				"end": end["date"],
			}
		)
		previous = {key: end[key] for key in ("strategy", "benchmark")}
	monthly = {key: [100.0] for key in peaks}
	month_last = {}
	for row in daily:
		month_last[row["date"][:7]] = row
	for row in month_last.values():
		for key in peaks:
			monthly[key].append(row[key])
	monthly_dd = {}
	for key, values in monthly.items():
		peak, minimum = 100.0, 0.0
		for value in values:
			peak = max(peak, value)
			minimum = min(minimum, value / peak - 1)
		monthly_dd[key] = minimum
	return {
		"annual_returns": annual,
		"drawdown_curve": drawdowns,
		"rolling_excess": rolling,
		"monthly_drawdown": monthly_dd,
	}


def _ranking_diagnostics(holdings: list[dict]) -> dict:
	correlations, retention, durations = [], [], []
	active: dict[tuple[str, int], date] = {}
	regimes: dict[str, list[dict]] = defaultdict(list)
	for index, row in enumerate(holdings):
		start = date.fromisoformat(row["execution_date"])
		keys = {(symbol, 1 if weight > 0 else -1) for symbol, weight in row["weights"].items()}
		for key in set(active) - keys:
			durations.append((start - active.pop(key)).days)
		for key in keys - set(active):
			active[key] = start
		if index:
			before = {
				item["symbol"]: rank for rank, item in enumerate(holdings[index - 1]["scores"])
			}
			after = {item["symbol"]: rank for rank, item in enumerate(row["scores"])}
			n = len(before)
			correlations.append(
				1
				- 6
				* sum((before[symbol] - after[symbol]) ** 2 for symbol in before)
				/ (n * (n * n - 1))
			)
			old_longs = {
				symbol for symbol, weight in holdings[index - 1]["weights"].items() if weight > 0
			}
			longs = {symbol for symbol, weight in row["weights"].items() if weight > 0}
			retention.append(len(old_longs & longs) / len(old_longs))
		if row["complete"]:
			regimes[row["regime"]].append(row)
	end = date.fromisoformat(holdings[-1]["end_date"])
	durations.extend((end - start).days for start in active.values())
	complete = [row for row in holdings if row["complete"]]
	return {
		"rank_persistence": mean(correlations) if correlations else None,
		"top_retention": mean(retention) if retention else None,
		"average_holding_days": mean(durations) if durations else None,
		"holding_duration_status": "Observed signed-position spells; final and initial spells are boundary-censored.",
		"top_beats_bottom_rate": mean(row["top_return"] > row["bottom_return"] for row in complete)
		if complete
		else None,
		"average_top_return": mean(row["top_return"] for row in complete) if complete else None,
		"average_bottom_return": mean(row["bottom_return"] for row in complete)
		if complete
		else None,
		"average_top_bottom_spread": mean(
			row["top_return"] - row["bottom_return"] for row in complete
		)
		if complete
		else None,
		"positive_net_spread_rate": mean(row["period_return"] > 0 for row in complete)
		if complete and any(w < 0 for w in complete[0]["weights"].values())
		else None,
		"ranking_metric_status": "Spearman of deterministic full ranks; top retention is long-basket overlap; ties use the model symbol tie-break.",
		"regime_performance": [
			{
				"regime": regime,
				"periods": len(rows),
				"hit_rate": mean(row["period_return"] > row["benchmark_return"] for row in rows),
				"average_return": mean(row["period_return"] for row in rows),
				"average_excess": mean(
					row["period_return"] - row["benchmark_return"] for row in rows
				),
			}
			for regime, rows in sorted(regimes.items())
		],
	}


def _sample_chart(points: list[dict], keys: tuple[str, ...], limit: int = 400) -> list[dict]:
	"""Bound publication size while retaining each time bucket's extrema and endpoints."""
	if len(points) <= limit:
		return points
	buckets = max(1, (limit - 2) // (2 * len(keys)))
	width = math.ceil((len(points) - 2) / buckets)
	selected = {0, len(points) - 1}
	for start in range(1, len(points) - 1, width):
		indices = range(start, min(start + width, len(points) - 1))
		for key in keys:
			selected.add(min(indices, key=lambda index: points[index][key]))
			selected.add(max(indices, key=lambda index: points[index][key]))
	return [points[index] for index in sorted(selected)]


def _simulate(prepared: dict, params: BacktestParams, mode: str) -> dict:
	prices, sessions = prepared["prices"], prepared["sessions"]
	cash, nav, benchmark = 100.0, 100.0, 100.0
	positions: dict[str, float] = {}
	curve = [{"date": prepared["period"]["first_execution"], "strategy": 100.0, "benchmark": 100.0}]
	daily = [curve[0].copy()]
	holdings, completed_returns, cash_returns, benchmark_returns = [], [], [], []
	contributions = {symbol: {"long": 0.0, "short": 0.0} for symbol in SECTORS}
	score_contributions: dict[str, dict[str, list[float]]] = defaultdict(
		lambda: {"long": [], "short": []}
	)
	actual_costs = {"trading": 0.0, "funding": 0.0, "borrow": 0.0}
	total_turnover, ruined = 0.0, False
	terminal_date = None
	for index, decision in enumerate(prepared["decisions"]):
		start = decision["execution"]
		end = prepared["boundaries"][index + 1][2]
		period_start_nav = nav
		weights = target_weights(mode, [row["symbol"] for row in decision["scores"]], params.top_n)
		for side in ("long", "short"):
			side_weights = {
				symbol: abs(weight)
				for symbol, weight in weights.items()
				if (weight > 0) == (side == "long")
			}
			gross = sum(side_weights.values())
			if gross:
				components: dict[str, float] = defaultdict(float)
				for symbol, weight in side_weights.items():
					for factor, value in sector_score_components(
						decision["state"], decision["momentum"][symbol], symbol
					).items():
						components[factor] += value * weight / gross
				for factor, value in components.items():
					score_contributions[factor][side].append(value)
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
		daily[-1]["strategy"] = nav
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
					contributions[symbol]["long"] += pnl / 100
				else:
					short_pnl += pnl
					contributions[symbol]["short"] += pnl / 100
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
				daily.append({"date": str(current), "strategy": nav, "benchmark": benchmark})
				break
			daily.append({"date": str(current), "strategy": nav, "benchmark": benchmark})
		if not ruined and index == len(prepared["decisions"]) - 1:
			liquidation_notional = sum(abs(value) for value in positions.values())
			liquidation_turnover = liquidation_notional / nav
			liquidation_cost = liquidation_notional * params.cost_bps / 10000
			nav -= liquidation_cost
			cash, positions = nav, {}
			if nav <= 0:
				ruined, terminal_date, nav = True, str(end), 0.0
		trading_cost += liquidation_cost
		daily[-1]["strategy"] = nav
		actual_costs["trading"] += trading_cost / 100
		actual_costs["funding"] += funding_cost / 100
		actual_costs["borrow"] += borrow_cost / 100
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
				"regime": classify_regime(decision["state"]),
				"top_return": prices[decision["scores"][0]["symbol"]][last_day]
				/ prices[decision["scores"][0]["symbol"]][start]
				- 1,
				"bottom_return": prices[decision["scores"][-1]["symbol"]][last_day]
				/ prices[decision["scores"][-1]["symbol"]][start]
				- 1,
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
		periods_per_year=prepared["period"]["periods_per_year"],
	)
	benchmark_stats = performance_statistics(
		benchmark_returns,
		cash_returns,
		[0.0] * len(benchmark_returns),
		[row["benchmark"] for row in curve],
		max(elapsed, 1),
		0.0,
		periods_per_year=prepared["period"]["periods_per_year"],
	)
	benchmark_stats["hit_rate_basis"] = "positive completed benchmark periods"
	stats["hit_rate_basis"] = "completed strategy periods beating SPY"
	research = _daily_research(daily, prepared["calendar"])
	for key, statistics in (("strategy", stats), ("benchmark", benchmark_stats)):
		statistics["max_drawdown_daily"] = min(row[key] for row in research["drawdown_curve"])
		statistics["max_drawdown"] = statistics["max_drawdown_daily"]
		statistics["max_drawdown_monthly"] = research["monthly_drawdown"][key]
	del research["monthly_drawdown"]
	research["drawdown_curve"] = _sample_chart(
		research["drawdown_curve"], ("strategy", "benchmark")
	)
	research["rolling_excess"] = _sample_chart(research["rolling_excess"], ("value",))
	stats["benchmark_total_return"] = curve[-1]["benchmark"] / 100 - 1
	benchmark_stats["benchmark_total_return"] = benchmark_stats["total_return"]
	if ruined:
		stats["hit_rate"] = None
		stats["metric_status"]["hit_rate"] = "terminal_insolvency"
	if elapsed == 0:
		stats["annualized_turnover"] = None
		stats["metric_status"]["annualized_turnover"] = "zero_elapsed_time"
	long_gross, short_gross = {"extreme1": (2, 2), "ranked3": (1, 1), "longonly3": (2.1, 0)}[mode]
	rank_weights = (
		[1.0] if params.top_n == 1 else [0.5] + [0.5 / (params.top_n - 1)] * (params.top_n - 1)
	)
	return {
		"strategy": {
			"id": mode,
			"label": {
				"extreme1": "Extreme +200% / -200%",
				"ranked3": f"Ranked {params.top_n} +100% / -100%",
				"longonly3": "Long only 100% / 65% / 45%",
			}[mode],
			"weights": {
				"extreme1": [2, -2],
				"ranked3": rank_weights + [-value for value in rank_weights],
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
		"benchmark_stats": benchmark_stats,
		**research,
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
			"drawdown_sampling": "daily closes, including trade costs and terminal insolvency",
			"ranking_return_frequency": params.rebalance,
			"ranking_return_basis": "Arithmetic means of complete selected-frequency cycles; unlevered top/bottom sector total returns before strategy costs.",
			"chart_sampling": "At most 400 extrema-preserving points per daily or rolling chart; all statistics use complete daily marks.",
			**_ranking_diagnostics(holdings),
			"attribution": [
				{
					"symbol": symbol,
					"long_contribution": values["long"],
					"short_contribution": values["short"],
					"total_contribution": sum(values.values()),
				}
				for symbol, values in contributions.items()
			],
			"attribution_basis": "Realized dollar PnL divided by initial NAV; sums across sectors less costs reconcile total return before any insolvency cap.",
			"cost_contributions": actual_costs,
			"insolvency_cap_contribution": stats["total_return"]
			- sum(sum(values.values()) for values in contributions.values())
			+ sum(actual_costs.values()),
			"score_attribution": [
				{
					"factor": factor,
					"average_long_score_points": mean(values["long"]) if values["long"] else None,
					"average_short_score_points": mean(values["short"])
					if values["short"]
					else None,
				}
				for factor, values in score_contributions.items()
			],
			"score_attribution_basis": "Average gross-normalized basket score points, excluding base 50; descriptive model decomposition, not causal return attribution.",
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
