"""Causal, descriptive market research over validated daily observations.

All composites are deterministic research rules, not calibrated probabilities.
The same calculations operate on explicitly labelled synthetic and real inputs.
"""

from __future__ import annotations

import math
from bisect import bisect_right, insort
from datetime import UTC, date, datetime, time
from functools import cached_property
from statistics import fmean, median, stdev
from typing import Any
from zoneinfo import ZoneInfo

from radar.data import DataError, Dataset
from radar.engine import (
	MODEL_VERSION,
	SECTORS,
	_History,
	_macro_snapshot,
	_month_end,
	score_sectors,
	sector_score_components,
)

ANALYTICS_VERSION = "1.0.0-research-unvalidated"
NY = ZoneInfo("America/New_York")
ASSETS = ("SPY", "QQQ", "XLF", "XLK", "XLE", "GLD", "USO", "UUP", "TLT", "CPER")
FX_PAIRS = ("EURUSD", "USDJPY", "USDCHF", "GBPUSD", "AUDUSD", "USDCAD", "USDCNH", "AUDJPY")
FX_UNITS = {
	"EURUSD": "USD/EUR",
	"USDJPY": "JPY/USD",
	"USDCHF": "CHF/USD",
	"GBPUSD": "USD/GBP",
	"AUDUSD": "USD/AUD",
	"USDCAD": "CAD/USD",
	"USDCNH": "CNH/USD",
	"AUDJPY": "JPY/AUD",
}
RATES = ("DGS2", "DGS5", "DGS10", "DGS30")
TITLES = {
	"risk": "Multi-horizon risk research",
	"changes": "What changed today",
	"anomalies": "Anomaly radar",
	"correlations": "Cross-asset correlations",
	"rates": "Rates regime",
	"volatility": "Volatility regime",
	"fx": "FX regime",
	"sectors": "Sector and style allocation",
	"playbook": "Regime playbook",
	"analogues": "Historical regime matches",
}


def _rounded(value: Any) -> Any:
	return round(value, 6) if isinstance(value, float) and math.isfinite(value) else value


def _metric(label: str, value: Any, unit: str = "text") -> dict:
	return {"label": label, "value": _rounded(value), "unit": unit}


def _table(title: str, columns: list[str], rows: list[list]) -> dict:
	return {
		"title": title,
		"columns": columns,
		"rows": [[_rounded(v) for v in row] for row in rows],
	}


def _section(
	key: str, summary: str, *, status: str = "ready", metrics=None, tables=None, charts=None
) -> dict:
	return {
		"status": status,
		"title": TITLES[key],
		"summary": summary,
		"metrics": metrics or [],
		"tables": tables or [],
		"charts": charts or [],
	}


def _chart(title: str, unit: str, series: list[tuple[str, list[tuple[Any, float | None]]]]) -> dict:
	return {
		"title": title,
		"unit": unit,
		"series": [
			{
				"label": label,
				"points": [{"date": str(day), "value": _rounded(value)} for day, value in points],
			}
			for label, points in series
		],
	}


def _clip(value: float, bound: float = 1) -> float:
	return max(-bound, min(bound, value))


def _difference(left: float | None, right: float | None) -> float | None:
	return None if left is None or right is None else left - right


def _ratio(left: float | None, right: float | None) -> float | None:
	if left is None or right is None or abs(right) < 1e-12:
		return None
	value = left / right
	return value if math.isfinite(value) else None


def _zscore(value: float | None, history: list[float | None], minimum: int = 60) -> float | None:
	valid = [v for v in history if v is not None]
	if value is None or len(valid) < minimum:
		return None
	deviation = stdev(valid)
	return (
		(value - fmean(valid)) / deviation
		if deviation > 1e-12
		else (0.0 if abs(value - fmean(valid)) < 1e-12 else None)
	)


def _percentile(value: float | None, history: list[float | None]) -> float | None:
	valid = [v for v in history if v is not None]
	if value is None or len(valid) < 60:
		return None
	return 100 * (sum(v < value for v in valid) + 0.5 * sum(v == value for v in valid)) / len(valid)


def _correlation(left: list[float | None], right: list[float | None], minimum: int) -> float | None:
	pairs = [(a, b) for a, b in zip(left, right, strict=True) if a is not None and b is not None]
	if len(pairs) < minimum:
		return None
	x, y = zip(*pairs, strict=True)
	xm, ym = fmean(x), fmean(y)
	xs, ys = sum((v - xm) ** 2 for v in x), sum((v - ym) ** 2 for v in y)
	if min(xs, ys) < 1e-24:
		return None
	return _clip(sum((a - xm) * (b - ym) for a, b in pairs) / math.sqrt(xs * ys), 1)


class _Inputs:
	"""Materialize daily point-in-time observations, excluding unavailable revisions."""

	def __init__(self, dataset: Dataset, now: datetime) -> None:
		self.dataset, self.now = dataset, now
		local = now.astimezone(NY)
		eligible = [
			day
			for day in dataset.calendar
			if day < local.date() or (day == local.date() and local.time() >= time(16, 30))
		]
		self.expected = (
			eligible[-1]
			if eligible and dataset.calendar[0] <= local.date() <= dataset.calendar[-1]
			else None
		)
		self.sessions = [
			day
			for day in dataset.calendar
			if day <= min(dataset.as_of, self.expected or dataset.as_of)
		]
		self.valid = (
			self.expected is not None
			and dataset.generated_at <= now
			and dataset.as_of <= local.date()
		)
		self.index = len(self.sessions) - 1
		self.arrays: dict[str, list[float | None]] = {}
		self.observation_dates: dict[str, list[date | None]] = {}
		self.errors: dict[str, str] = {}
		self.return_cache: dict[tuple[str, int], list[float | None]] = {}
		self.risk_cache: dict[tuple[int, int], dict | None] = {}
		self.return_basis = {
			series.price_basis
			for name, series in dataset.series.items()
			if name.endswith("_TR")
			and series.price_basis in {"total_return_net", "total_return_gross"}
		}

	def values(self, name: str) -> list[float | None]:
		if name in self.arrays:
			return self.arrays[name]
		series = self.dataset.series.get(name)
		result: list[float | None] = [None] * len(self.sessions)
		dates: list[date | None] = [None] * len(self.sessions)
		if series is None:
			self.errors[name] = "Missing series"
		elif name.endswith("_TR") and (
			series.price_basis not in {"total_return_net", "total_return_gross"}
			or series.unit != "index"
			or series.currency != "USD"
			or len(self.return_basis) != 1
		):
			self.errors[name] = "Requires consistently defined USD total-return indices"
		elif name in FX_PAIRS and (series.price_basis != "fx" or series.unit != FX_UNITS[name]):
			self.errors[name] = "Requires FX quote units matching the currency-pair orientation"
		elif (
			name not in FX_PAIRS
			and not name.endswith("_TR")
			and (
				(series.price_basis, series.unit)
				!= (
					("index", "index")
					if name
					in {"VIXCLS", "VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "MOVE"}
					else ("rate", "percent")
				)
			)
		):
			self.errors[name] = "Incompatible units or price basis"
		else:
			events = sorted(series.observations, key=lambda row: row.available_at)
			cursor = 0
			known = {}
			known_dates = []
			for index, day in enumerate(self.sessions):
				cutoff = min(self.now, datetime.combine(day, time(23, 59, 59), NY))
				while cursor < len(events) and events[cursor].available_at <= cutoff:
					row = events[cursor]
					if row.date not in known:
						insort(known_dates, row.date)
					known[row.date] = row.value
					cursor += 1
				position = bisect_right(known_dates, day) - 1
				latest = known_dates[position] if position >= 0 else None
				if name.endswith("_TR") or name in FX_PAIRS:
					result[index] = known.get(day)
					dates[index] = day if day in known else None
				elif latest is not None and (day - latest).days <= 3:
					result[index] = known[latest]
					dates[index] = latest
		self.arrays[name] = result
		self.observation_dates[name] = dates
		return result

	def aligned(self, names: tuple | list, index: int | None = None) -> bool:
		"""Only combine simultaneous rate/volatility levels in spread calculations."""
		index = self.index if index is None else index
		if not 0 <= index < len(self.sessions):
			return False
		for name in names:
			self.values(name)
		dates = [self.observation_dates[name][index] for name in names]
		return bool(dates) and None not in dates and len(set(dates)) == 1

	def at(self, name: str, index: int | None = None) -> float | None:
		index = self.index if index is None else index
		return self.values(name)[index] if 0 <= index < len(self.sessions) else None

	def change(self, name: str, horizon: int = 1) -> list[float | None]:
		key = (name, horizon)
		if key not in self.return_cache:
			values = self.values(name)
			is_return = name.endswith("_TR") or name in FX_PAIRS
			result = []
			for i, value in enumerate(values):
				past = values[i - horizon] if i >= horizon else None
				complete = i >= horizon and all(v is not None for v in values[i - horizon : i + 1])
				result.append(
					(_difference(_ratio(value, past), 1.0) if is_return else value - past)
					if complete and value is not None and past is not None
					else None
				)
			self.return_cache[key] = result
		return self.return_cache[key]

	def delta(self, name: str, horizon: int = 1, index: int | None = None) -> float | None:
		index = self.index if index is None else index
		return self.change(name, horizon)[index] if 0 <= index < len(self.sessions) else None

	def corr(self, left: str, right: str, window: int, index: int | None = None) -> float | None:
		index = self.index if index is None else index
		start = max(0, index - window + 1)
		return _correlation(
			self.change(left)[start : index + 1],
			self.change(right)[start : index + 1],
			math.ceil(window * 0.75),
		)

	def rv(self, window: int, index: int | None = None) -> float | None:
		index = self.index if index is None else index
		values = self.change("SPY_TR")[max(0, index - window + 1) : index + 1]
		if len(values) != window or any(v is None for v in values):
			return None
		return 100 * stdev([math.log1p(v) for v in values]) * math.sqrt(252)

	def status(self, names: tuple | list) -> str:
		count = sum(self.at(name) is not None for name in names)
		return "ready" if count == len(names) else "partial" if count else "unavailable"

	@cached_property
	def curve(self) -> list[float | None]:
		return [
			_difference(a, b) if self.aligned(("DGS10", "DGS2"), i) else None
			for i, (a, b) in enumerate(zip(self.values("DGS10"), self.values("DGS2"), strict=True))
		]


def _direction(score: float | None) -> str:
	return (
		"Unavailable"
		if score is None
		else "Bullish"
		if score > 20
		else "Bearish"
		if score < -20
		else "Neutral"
	)


def _derived_status(data: _Inputs, names: tuple | list, values: tuple | list) -> str:
	status = data.status(names)
	return "partial" if status == "ready" and any(value is None for value in values) else status


def _risk_at(data: _Inputs, index: int, horizon: int) -> dict | None:
	key = (index, horizon)
	if key in data.risk_cache:
		return data.risk_cache[key]
	factors = []
	for name, label, sign, weight in (
		("SPY_TR", "Equity momentum", 1, 0.35),
		("DGS10", "Yield shock", -1, 0.15),
		("VIXCLS", "Volatility change", -1, 0.20),
		("BAMLH0A0HYM2", "Credit spread change", -1, 0.15),
		("UUP_TR", "USD tightening proxy", -1, 0.10),
	):
		values = data.change(name, horizon)
		z = _zscore(values[index] if index >= 0 else None, values[max(0, index - 252) : index])
		if z is None:
			data.risk_cache[key] = None
			return None
		factors.append(
			{
				"factor": label,
				"normalized": _clip(z / 3),
				"weight": weight,
				"contribution": 100 * weight * sign * _clip(z / 3),
			}
		)
	corr = data.corr("SPY_TR", "TLT_TR", 20, index)
	if corr is None:
		data.risk_cache[key] = None
		return None
	factors.append(
		{
			"factor": "Equity/bond co-movement",
			"normalized": max(0, corr),
			"weight": 0.05,
			"contribution": -5 * max(0, corr),
		}
	)
	score = sum(row["contribution"] for row in factors)
	result = {
		"score": score,
		"direction": _direction(score),
		"strength": abs(score),
		"factors": factors,
	}
	data.risk_cache[key] = result
	return result


def _risk(data: _Inputs) -> dict:
	items = [
		(label, horizon, _risk_at(data, data.index, horizon))
		for label, horizon in (("1D", 1), ("1W", 5), ("1M", 20))
	]
	valid = [item[2] for item in items if item[2] is not None]
	spread = (
		max(item["score"] for item in valid) - min(item["score"] for item in valid)
		if len(valid) == 3
		else None
	)
	divergence = (
		"Unavailable"
		if spread is None
		else "HIGH"
		if spread >= 80
		else "MID"
		if spread >= 35
		else "LOW"
	)
	summary = "; ".join(
		f"{label}: {item['direction'] if item else 'unavailable'}" for label, _, item in items
	)
	summary += f". {divergence} horizon divergence. Strength is score magnitude, not a forecast probability. Missing or flat-variance shock histories can prevent normalization."
	metrics = [
		_metric(f"{label} risk score", item["score"] if item else None, "score")
		for label, _, item in items
	]
	metrics += [
		_metric("Horizon divergence", divergence),
		_metric(
			"Horizon alignment",
			"Unavailable"
			if len(valid) != 3
			else "All horizons aligned"
			if len({item["direction"] for item in valid}) == 1
			else "Conflicting horizon directions",
		),
		_metric("1M signal strength", valid[-1]["strength"] if len(valid) == 3 else None, "score"),
	]
	tables = [
		_table(
			"Risk factors: signed contributions",
			["Horizon", "Factor", "Normalized input", "Weight (%)", "Contribution (points)"],
			[
				[label, row["factor"], row["normalized"], 100 * row["weight"], row["contribution"]]
				for label, _, item in items
				if item
				for row in item["factors"]
			],
		)
	]
	charts = [
		_chart(
			"Risk scores through time",
			"score",
			[
				(
					label,
					[
						(
							data.sessions[i],
							result["score"] if (result := _risk_at(data, i, horizon)) else None,
						)
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
				for label, horizon, _ in items
			],
		)
	]
	return _section(
		"risk",
		summary,
		status="ready" if len(valid) == 3 else "partial" if valid else "unavailable",
		metrics=metrics,
		tables=tables,
		charts=charts,
	)


def _changes_and_anomalies(data: _Inputs) -> tuple[dict, dict]:
	rows, anomaly_rows, acceleration_rows = [], [], []
	for name in (
		*[f"{symbol}_TR" for symbol in ASSETS],
		"DGS10",
		"DFII10",
		"T10YIE",
		"VIXCLS",
		"BAMLH0A0HYM2",
		"MOVE",
		*FX_PAIRS,
	):
		values = data.change(name)
		change = data.delta(name)
		prior = data.delta(name, index=data.index - 1)
		unit = (
			"%"
			if name.endswith("_TR") or name in FX_PAIRS
			else "bp"
			if name in {"DGS10", "DFII10", "T10YIE", "BAMLH0A0HYM2"}
			else "points"
		)
		factor = 100 if unit in {"%", "bp"} else 1
		z = _zscore(change, values[max(0, data.index - 252) : data.index])
		pct = _percentile(change, values[max(0, data.index - 252) : data.index])
		acceleration = _difference(change, prior)
		acceleration_rows.append(
			[
				name.removesuffix("_TR"),
				unit,
				*[
					None
					if (
						value := _difference(
							data.delta(name, index=i), data.delta(name, index=i - 1)
						)
					)
					is None
					else value * factor
					for i in range(max(0, data.index - 4), data.index + 1)
				],
			]
		)
		rows.append(
			[
				name.removesuffix("_TR"),
				None if change is None else change * factor,
				unit,
				None if acceleration is None else acceleration * factor,
				z,
				pct,
			]
		)
		if z is not None:
			anomaly_rows.append(
				[
					name.removesuffix("_TR"),
					z,
					pct,
					"HIGH" if abs(z) >= 3 else "ELEVATED" if abs(z) >= 2 else "ORDINARY",
					None if change is None else change * factor,
					unit,
				]
			)
	anomaly_rows.sort(key=lambda row: (-abs(row[1]), row[0]))
	strong = [row for row in anomaly_rows if abs(row[1]) >= 2]
	most = anomaly_rows[0] if anomaly_rows else None
	change_summary = (
		f"Largest standardized daily move: {most[0]} ({most[1]:+.2f}σ). "
		if most
		else "Daily change normalization is unavailable. "
	)
	change_summary += "Acceleration is today's change minus yesterday's; reference distributions exclude today's move. Prices use total returns; rates use basis-point changes."
	changes = _section(
		"changes",
		change_summary,
		status="ready"
		if all(row[1] is not None for row in rows)
		else "partial"
		if any(row[1] is not None for row in rows)
		else "unavailable",
		metrics=[_metric("Elevated daily moves", len(strong), "count")],
		tables=[
			_table(
				"Changes and acceleration",
				[
					"Series",
					"1D change",
					"Unit",
					"Acceleration",
					"Prior-history z",
					"Percentile (%)",
				],
				rows,
			),
			_table(
				"Five-session signal acceleration",
				["Series", "Unit", *[str(day) for day in data.sessions[-5:]]],
				acceleration_rows,
			),
		],
	)
	anomalies = _section(
		"anomalies",
		f"{len(strong)} series exceed |z| ≥ 2; rankings use absolute daily z-scores against the preceding 252 sessions (minimum 60). These are descriptive outliers, not event probabilities.",
		status="ready" if anomaly_rows else "unavailable",
		metrics=[
			_metric("Largest absolute z", abs(most[1]) if most else None, "score"),
			_metric("Elevated anomalies", len(strong), "count"),
		],
		tables=[
			_table(
				"Anomalies ranked by magnitude",
				["Series", "Signed z", "Percentile (%)", "Severity", "1D change", "Unit"],
				anomaly_rows,
			)
		],
	)
	return changes, anomalies


def _correlations(data: _Inputs) -> dict:
	tables = []
	for window in (20, 60):
		tables.append(
			_table(
				f"{window}-session total-return correlation",
				["Asset", *ASSETS],
				[
					[left, *[data.corr(f"{left}_TR", f"{right}_TR", window) for right in ASSETS]]
					for left in ASSETS
				],
			)
		)
	current20 = data.corr("SPY_TR", "TLT_TR", 20)
	current60 = data.corr("SPY_TR", "TLT_TR", 60)
	gap = _difference(current20, current60)
	break_label = (
		"Unavailable"
		if gap is None
		else "Correlation break"
		if abs(gap) >= 0.35
		else "Broadly stable"
	)
	charts = [
		_chart(
			"Equity/bond rolling correlation",
			"correlation",
			[
				(
					f"{window} sessions",
					[
						(data.sessions[i], data.corr("SPY_TR", "TLT_TR", window, i))
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
				for window in (20, 60)
			],
		)
	]
	charts.append(
		_chart(
			"Equity/bond correlation break history",
			"correlation",
			[
				(
					"20D−60D",
					[
						(
							data.sessions[i],
							_difference(
								data.corr("SPY_TR", "TLT_TR", 20, i),
								data.corr("SPY_TR", "TLT_TR", 60, i),
							),
						)
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
			],
		)
	)
	return _section(
		"correlations",
		f"{break_label}: the 20-session minus 60-session SPY/TLT correlation is compared with a 0.35 threshold. Correlations join identical daily intervals and require at least 75% coverage; constant series return unavailable.",
		status=_derived_status(data, [f"{s}_TR" for s in ASSETS], [current20, current60]),
		metrics=[
			_metric("Equity/bond 20D", current20, "correlation"),
			_metric("Equity/bond 60D", current60, "correlation"),
			_metric("20D−60D difference", gap, "correlation"),
			_metric("Correlation regime", break_label),
		],
		tables=tables,
		charts=charts,
	)


def _rates(data: _Inputs) -> dict:
	today = {name: data.at(name) for name in RATES}
	spreads = {
		label: _difference(today[long], today[short]) if data.aligned((long, short)) else None
		for label, short, long in (
			("2s10s", "DGS2", "DGS10"),
			("5s30s", "DGS5", "DGS30"),
			("2s30s", "DGS2", "DGS30"),
			("10s30s", "DGS10", "DGS30"),
		)
	}
	level = fmean(today.values()) if data.aligned(RATES) else None
	curvature = (
		2 * today["DGS5"] - today["DGS2"] - today["DGS10"]
		if data.aligned(("DGS2", "DGS5", "DGS10"))
		else None
	)
	deltas = [data.delta(name, 20) for name in RATES]
	level_change = (
		fmean(deltas)
		if all(v is not None for v in deltas)
		and data.aligned(RATES)
		and data.aligned(RATES, data.index - 20)
		else None
	)
	slope_change = (
		_difference(data.curve[-1], data.curve[data.index - 20]) if data.index >= 20 else None
	)
	regime = (
		"Unavailable"
		if level_change is None or slope_change is None
		else "STABLE / MIXED"
		if abs(level_change) < 0.05 or abs(slope_change) < 0.05
		else ("BULL " if level_change < 0 else "BEAR ")
		+ ("STEEPENER" if slope_change > 0 else "FLATTENER")
	)
	duration = (
		"Unavailable"
		if level_change is None
		else "Long-duration tailwind"
		if level_change < -0.05
		else "Long-duration headwind"
		if level_change > 0.05
		else "Neutral duration signal"
	)
	strength = None if level_change is None else min(100, abs(level_change) / 0.50 * 100)
	metrics = [
		_metric("Rates regime", regime),
		_metric("Curve level", level, "percent"),
		_metric("2s10s slope", spreads["2s10s"], "percentage_points"),
		_metric("2×5Y−2Y−10Y curvature", curvature, "percentage_points"),
		_metric("Duration research bias", duration),
		_metric("Duration signal strength", strength, "score"),
		*[
			_metric(label, value, "percentage_points")
			for label, value in spreads.items()
			if label != "2s10s"
		],
		*[
			_metric(label, data.at(name), unit)
			for name, label, unit in (
				("DFII10", "10Y real yield", "percent"),
				("T5YIE", "5Y breakeven", "percent"),
				("T10YIE", "10Y breakeven", "percent"),
				("T5YIFR", "5Y5Y forward inflation", "percent"),
				("MOVE", "MOVE", "index"),
			)
		],
		_metric(
			"10Y nominal−real−breakeven residual",
			_difference(_difference(today["DGS10"], data.at("DFII10")), data.at("T10YIE"))
			if data.aligned(("DGS10", "DFII10", "T10YIE"))
			else None,
			"percentage_points",
		),
	]
	curve_rows = [
		[
			name.removeprefix("DGS") + "Y",
			*[data.at(name, data.index - offset) for offset in (0, 1, 20, 60)],
		]
		for name in RATES
	]
	charts = [
		_chart(
			"Treasury curve snapshots",
			"percent",
			[
				(
					label,
					[
						(
							name.removeprefix("DGS") + "Y",
							data.at(name, data.index - offset)
							if data.aligned(RATES, data.index - offset)
							else None,
						)
						for name in RATES
					],
				)
				for label, offset in (
					("Today", 0),
					("Prior session", 1),
					("1M / 20 sessions", 20),
					("3M / 60 sessions", 60),
				)
			],
		),
		_chart(
			"Nominal, real and breakeven yields",
			"percent",
			[
				(
					name,
					[
						(data.sessions[i], data.at(name, i))
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
				for name in ("DGS10", "DFII10", "T10YIE")
			],
		),
	]
	charts.append(
		_chart(
			"Treasury curve-spread history",
			"percentage_points",
			[
				(
					label,
					[
						(
							data.sessions[i],
							_difference(data.at(long, i), data.at(short, i))
							if data.aligned((long, short), i)
							else None,
						)
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
				for label, short, long in (
					("2s10s", "DGS2", "DGS10"),
					("5s30s", "DGS5", "DGS30"),
					("2s30s", "DGS2", "DGS30"),
					("10s30s", "DGS10", "DGS30"),
				)
			],
		)
	)
	decomposition_history = {
		"Curve level": [
			fmean(data.at(name, i) for name in RATES) if data.aligned(RATES, i) else None
			for i in range(len(data.sessions))
		],
		"2s10s slope": data.curve,
		"2×5Y−2Y−10Y curvature": [
			2 * data.at("DGS5", i) - data.at("DGS2", i) - data.at("DGS10", i)
			if data.aligned(("DGS2", "DGS5", "DGS10"), i)
			else None
			for i in range(len(data.sessions))
		],
		**{
			label: data.values(name)
			for name, label in (
				("DFII10", "10Y real yield"),
				("T5YIE", "5Y breakeven"),
				("T10YIE", "10Y breakeven"),
				("T5YIFR", "5Y5Y forward inflation"),
			)
		},
	}
	percentile_rows = [
		[label, values[-1], _percentile(values[-1], values[max(0, data.index - 252) : data.index])]
		for label, values in decomposition_history.items()
	]
	return _section(
		"rates",
		f"{regime}; {duration.lower()}. Classification uses 20-session changes in average 2Y/5Y/10Y/30Y yield and 2s10s slope, with a 5bp noise band. Strength is scaled yield movement, not confidence. Supplied FRED 5Y5Y is used directly; no linear approximation.",
		status=_derived_status(
			data,
			[*RATES, "DFII10", "T5YIE", "T10YIE", "T5YIFR", "MOVE"],
			[level_change, slope_change],
		),
		metrics=metrics,
		tables=[
			_table(
				"Treasury yields (%)",
				["Maturity", "Today", "Prior", "20 sessions ago", "60 sessions ago"],
				curve_rows,
			),
			_table(
				"Latest source dates",
				["Series", "Observation date"],
				[
					[
						name,
						str(data.observation_dates[name][-1])
						if data.observation_dates[name][-1]
						else None,
					]
					for name in RATES
				],
			),
			_table(
				"Rates and inflation historical percentiles",
				["Measure", "Current (%) / percentage points", "Prior 252-session percentile (%)"],
				percentile_rows,
			),
		],
		charts=charts,
	)


def _volatility(data: _Inputs) -> dict:
	iv, rv20 = data.at("VIXCLS"), data.rv(20)
	aligned_iv = data.aligned(("VIXCLS", "SPY_TR"))
	ratio = _ratio(iv, rv20) if aligned_iv else None
	vrp = _difference(iv, rv20) if aligned_iv else None
	ratio_history = [
		_ratio(data.at("VIXCLS", i), data.rv(20, i))
		if data.aligned(("VIXCLS", "SPY_TR"), i)
		else None
		for i in range(max(0, data.index - 252), data.index)
	]
	pct = _percentile(ratio, ratio_history)
	acceleration = _difference(data.rv(5), data.rv(20))
	term = _ratio(data.at("VIX9D"), data.at("VIX3M")) if data.aligned(("VIX9D", "VIX3M")) else None
	regime = (
		"Unavailable"
		if iv is None or ratio is None
		else "PANIC"
		if iv >= 40
		else "STRESS"
		if iv >= 30 or (term is not None and term >= 1.10)
		else "RICH"
		if ratio >= 1.5
		else "LOW/CHEAP"
		if iv < 15 or ratio < 1
		else "NORMAL"
	)
	bias = (
		"Demand for short-horizon protection elevated"
		if regime in {"PANIC", "STRESS"}
		else "Implied volatility rich to realized history"
		if regime == "RICH"
		else "Implied volatility low relative to rule thresholds"
		if regime == "LOW/CHEAP"
		else "Balanced volatility signal"
	)
	metrics = [
		_metric("Volatility regime", regime),
		_metric("VIX implied volatility", iv, "percent"),
		*[
			_metric(f"Realized volatility {window}D", data.rv(window), "percent")
			for window in (5, 10, 20, 60)
		],
		_metric("IV−RV20 premium", vrp, "percentage_points"),
		_metric("IV/RV20", ratio, "ratio"),
		_metric("IV/RV percentile", pct, "percent"),
		_metric("RV5−RV20 acceleration", acceleration, "percentage_points"),
		_metric("VIX9D/VIX3M", term, "ratio"),
		_metric(
			"3M−1M term slope",
			_difference(data.at("VIX3M"), iv) if data.aligned(("VIX3M", "VIXCLS")) else None,
			"percentage_points",
		),
		_metric(
			"2×3M−1M−6M term curvature",
			2 * data.at("VIX3M") - iv - data.at("VIX6M")
			if data.aligned(("VIX3M", "VIXCLS", "VIX6M"))
			else None,
			"percentage_points",
		),
		_metric(
			"Term structure",
			"Unavailable" if term is None else "Inverted" if term > 1 else "Upward / flat",
		),
		*[_metric(name, data.at(name), "index") for name in ("VVIX", "SKEW", "MOVE")],
		_metric(
			"MOVE/VIX",
			_ratio(data.at("MOVE"), iv) if data.aligned(("MOVE", "VIXCLS")) else None,
			"ratio",
		),
	]
	charts = [
		_chart(
			"Implied volatility term structure",
			"percent",
			[
				(
					"Current",
					[
						(label, data.at(name))
						for name, label in (
							("VIX9D", "9D"),
							("VIXCLS", "1M"),
							("VIX3M", "3M"),
							("VIX6M", "6M"),
							("VIX1Y", "1Y"),
						)
					],
				)
			],
		),
		_chart(
			"Implied versus realized volatility",
			"percent",
			[
				(
					label,
					[
						(
							data.sessions[i],
							data.at("VIXCLS", i) if window == 0 else data.rv(window, i),
						)
						for i in range(max(0, data.index - 119), data.index + 1)
					],
				)
				for label, window in (("VIX", 0), ("RV20", 20), ("RV60", 60))
			],
		),
	]
	charts.append(
		_chart(
			"12-month implied−realized volatility premium",
			"percentage_points",
			[
				(
					"VIX−RV20",
					[
						(
							data.sessions[i],
							_difference(data.at("VIXCLS", i), data.rv(20, i))
							if data.aligned(("VIXCLS", "SPY_TR"), i)
							else None,
						)
						for i in range(max(0, data.index - 251), data.index + 1)
					],
				)
			],
		)
	)
	return _section(
		"volatility",
		f"{regime}: {bias}. Realized volatility is annualized sample standard deviation of daily SPY total-return log changes (252 sessions/year). IV−RV is a descriptive volatility-point premium, not an expected option return. Combined measures require matching observation dates and adequate history; unavailable values remain null. MOVE/VIX compares distinct indices, not equivalent risks.",
		status=_derived_status(
			data,
			["SPY_TR", "VIXCLS", "VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "MOVE"],
			[ratio, vrp, term, pct],
		),
		metrics=metrics,
		charts=charts,
	)


def _fx_composites(data: _Inputs, index: int) -> tuple[float | None, float | None]:
	dollar, risk = [], []
	for name, orientation in (
		("EURUSD", -1),
		("USDJPY", 1),
		("USDCHF", 1),
		("GBPUSD", -1),
		("AUDUSD", -1),
		("USDCAD", 1),
		("USDCNH", 1),
	):
		values = data.change(name, 20)
		z = _zscore(values[index], values[max(0, index - 252) : index])
		if z is not None:
			dollar.append(orientation * _clip(z / 3) * 100)
	for name, orientation in (("AUDUSD", 1), ("AUDJPY", 1), ("USDCNH", -1)):
		values = data.change(name, 20)
		z = _zscore(values[index], values[max(0, index - 252) : index])
		if z is not None:
			risk.append(orientation * _clip(z / 3) * 100)
	return fmean(dollar) if len(dollar) == 7 else None, fmean(risk) if len(risk) == 3 else None


def _fx(data: _Inputs) -> dict:
	dollar, risk = _fx_composites(data, data.index)
	regime = (
		"Unavailable"
		if dollar is None or risk is None
		else "USD tightening / risk-off"
		if dollar > 20 and risk < -20
		else "Risk FX supported"
		if risk > 20
		else "USD weakening"
		if dollar < -20
		else "Mixed / range-bound"
	)
	tables = [
		_table(
			"Currency observations",
			["Pair", "Quote", "Quote unit", "1D return (%)", "20D return (%)"],
			[
				[
					name,
					data.at(name),
					FX_UNITS[name],
					None if (v := data.delta(name)) is None else v * 100,
					None if (v := data.delta(name, 20)) is None else v * 100,
				]
				for name in FX_PAIRS
			],
		)
	]
	for window in (20, 60):
		tables.append(
			_table(
				f"FX {window}-session return correlation",
				["Pair", *FX_PAIRS],
				[
					[left, *[data.corr(left, right, window) for right in FX_PAIRS]]
					for left in FX_PAIRS
				],
			)
		)
	tables.append(
		_table(
			"FX versus assets: 60-session correlation",
			["Pair", "SPY", "Gold", "Copper", "Oil", "Real-yield change"],
			[
				[
					name,
					*[
						data.corr(name, target, 60)
						for target in ("SPY_TR", "GLD_TR", "CPER_TR", "USO_TR", "DFII10")
					],
				]
				for name in FX_PAIRS
			],
		)
	)
	charts = [
		_chart(
			"USD and risk FX research scores",
			"score",
			[
				(
					label,
					[
						(data.sessions[i], _fx_composites(data, i)[component])
						for i in range(max(0, data.index - 119), data.index + 1)
					],
				)
				for label, component in (("USD strength", 0), ("Risk FX", 1))
			],
		)
	]
	return _section(
		"fx",
		f"{regime}. USD score signs seven pairs toward dollar strength; risk FX averages AUDUSD, AUDJPY and inverted USDCNH signals. Each uses its own trailing normalized 20-session return. Equal weights are research choices, not DXY weights. Real-yield correlations use changes, not yield levels.",
		status=_derived_status(
			data, [*FX_PAIRS, "SPY_TR", "GLD_TR", "CPER_TR", "USO_TR", "DFII10"], [dollar, risk]
		),
		metrics=[
			_metric("Dollar regime score", dollar, "score"),
			_metric("Risk FX score", risk, "score"),
			_metric("FX regime", regime),
		],
		tables=tables,
		charts=charts,
	)


def _sector_values(data: _Inputs) -> tuple[list[dict], dict, dict]:
	month_ends = [
		i
		for i, day in enumerate(data.sessions)
		if i + 1 < len(data.sessions) and data.sessions[i + 1].month != day.month
	]
	prior = [
		i for i in month_ends if data.sessions[i].replace(day=1) < data.sessions[-1].replace(day=1)
	][-60:]
	if len(prior) < 12:
		return [], {}, {}
	history = _History(data.dataset)
	monthly = []
	for index in reversed(prior):
		try:
			monthly.append(_macro_snapshot(history, _month_end(data.sessions[index])))
		except DataError:
			break
	if len(monthly) < 12:
		return [], {}, {}
	state = {}
	for factor, values in (
		("rates", data.values("DFII10")),
		("curve", data.curve),
		("inflation", data.values("T10YIE")),
		("vol", data.values("VIXCLS")),
		("credit", data.values("BAMLH0A0HYM2")),
	):
		reference = [snapshot[factor] for snapshot in monthly]
		z = (
			0.0
			if values[-1] is not None
			and all(v is not None for v in reference)
			and stdev(reference) < 1e-12
			else _zscore(values[-1], reference, 12)
		)
		if z is None:
			return [], {}, {}
		state[factor] = _clip(z / 2)
	current = data.sessions[-1]
	month_index = current.year * 12 + current.month - 1 - 6
	anchor_month = date(month_index // 12, month_index % 12 + 1, 1)
	anchor_days = [
		i
		for i, day in enumerate(data.sessions)
		if day.year == anchor_month.year and day.month == anchor_month.month
	]
	if not anchor_days:
		return [], {}, {}
	anchor = anchor_days[-1]
	momentum = {}
	for symbol in SECTORS:
		values = data.values(f"{symbol}_TR")
		if any(v is None for v in values[anchor:]):
			return [], {}, {}
		momentum[symbol] = values[-1] / values[anchor] - 1
	return score_sectors(state, momentum), state, momentum


def _contributions(symbol: str, state: dict, momentum: float) -> dict:
	return sector_score_components(state, momentum, symbol)


def _sectors(data: _Inputs) -> tuple[dict, list[dict], dict]:
	ranked, state, momentum = _sector_values(data)
	if not ranked:
		return (
			_section(
				"sectors",
				"Sector ranking requires twelve prior complete month-end macro snapshots, a matching six-month total-return history for all eleven sectors, and current available inputs. No default sector scores are substituted.",
				status="unavailable",
			),
			[],
			{},
		)
	rows, contributions = [], []
	for index, row in enumerate(ranked):
		symbol, raw = row["symbol"], row["score"]
		label = "OVERWEIGHT" if index < 3 else "UNDERWEIGHT" if index >= 8 else "NEUTRAL"
		rows.append([index + 1, symbol, raw, max(0, min(100, raw)), label, momentum[symbol] * 100])
		contributions.append(
			[symbol, 50, *_contributions(symbol, state, momentum[symbol]).values(), raw]
		)
	scores = {row["symbol"]: row["score"] for row in ranked}
	styles = {
		"Value": ("XLF", "XLE", "XLB"),
		"Quality proxy": ("XLV", "XLP"),
		"Low volatility proxy": ("XLU", "XLP", "XLV"),
		"Growth": ("XLK", "XLC", "XLY"),
		"High beta proxy": ("XLY", "XLI", "XLB"),
		"Bond proxies": ("XLU", "XLRE"),
	}
	style_rows = [
		[
			label,
			", ".join(symbols),
			fmean(scores[s] for s in symbols),
			"Favor"
			if fmean(scores[s] for s in symbols) >= 55
			else "Avoid"
			if fmean(scores[s] for s in symbols) <= 45
			else "Neutral",
		]
		for label, symbols in styles.items()
	]
	tables = [
		_table(
			"Current sector ranking",
			[
				"Rank",
				"Sector",
				"Raw score",
				"Display score (0–100)",
				"Preference",
				"6M momentum (%)",
			],
			rows,
		),
		_table(
			"Additive sector factor contributions",
			[
				"Sector",
				"Base",
				"Rates",
				"Curve",
				"Inflation",
				"Volatility",
				"Credit",
				"Legacy style",
				"Momentum",
				"Raw total",
			],
			contributions,
		),
		_table(
			"Style baskets: sector proxies",
			["Style", "Constituents", "Mean raw score", "Preference"],
			style_rows,
		),
		_table(
			"Normalized macro state",
			["Factor", "State (−1 to +1)"],
			[[label, value] for label, value in state.items()],
		),
	]
	summary = f"Current leaders: {', '.join(row['symbol'] for row in ranked[:3])}; laggards: {', '.join(row['symbol'] for row in ranked[-3:])}. Uses the exact {MODEL_VERSION} sector coefficients. Raw scores determine ranks; the 0–100 display clips extremes. Style baskets are sector proxies, not measured company fundamentals or factor portfolios."
	return (
		_section(
			"sectors",
			summary,
			metrics=[
				_metric("Top sector", ranked[0]["symbol"]),
				_metric("Bottom sector", ranked[-1]["symbol"]),
				_metric(
					"Best−worst score spread", ranked[0]["score"] - ranked[-1]["score"], "score"
				),
			],
			tables=tables,
		),
		ranked,
		state,
	)


def _playbook(data: _Inputs, ranked: list[dict], state: dict) -> dict:
	if not ranked:
		return _section(
			"playbook",
			"A complete sector and macro state is required before composing conditional preferences.",
			status="unavailable",
		)
	risk = _risk_at(data, data.index, 20)
	dollar, risk_fx = _fx_composites(data, data.index)
	stress = data.at("VIXCLS") is not None and data.at("VIXCLS") >= 30 or state["credit"] > 0.75
	strength = min(100, (ranked[0]["score"] - ranked[-1]["score"]) * 2)
	if risk is None or risk_fx is None or dollar is None:
		stance = "Incomplete cross-asset confirmation"
	elif stress:
		stance = "Defensive guardrail: review gross exposure and liquidity"
	elif risk["score"] < -20 or risk_fx < -20:
		stance = "Cautious: sector preferences face a risk headwind"
	else:
		stance = "Selective: sector preferences have no stress override"
	preferences = [
		["Favor", ", ".join(row["symbol"] for row in ranked[:3])],
		["Neutral", ", ".join(row["symbol"] for row in ranked[3:-3])],
		["Avoid", ", ".join(row["symbol"] for row in ranked[-3:])],
	]
	matrix = []
	for rates in (-1, 1):
		for vol in (-1, 1):
			for credit in (-1, 1):
				scenario = {**state, "rates": rates, "vol": vol, "credit": credit}
				order = score_sectors(scenario, dict.fromkeys(SECTORS, 0.0))
				matrix.append(
					[
						"Low real yields" if rates < 0 else "High real yields",
						"Low volatility" if vol < 0 else "High volatility",
						"Tight credit" if credit < 0 else "Wide credit",
						", ".join(row["symbol"] for row in order[:3]),
						", ".join(row["symbol"] for row in order[-3:]),
					]
				)
	triggers = [
		[
			"VIX ≥ 30 or credit state > +0.75",
			"Activate defensive review",
			"Active" if stress else "Inactive",
		],
		[
			"1M risk score < −20",
			"Flag macro headwind",
			"Unavailable" if risk is None else "Active" if risk["score"] < -20 else "Inactive",
		],
		[
			"Risk FX score < −20",
			"Flag risk-currency headwind",
			"Unavailable" if risk_fx is None else "Active" if risk_fx < -20 else "Inactive",
		],
		[
			"USD score > +20",
			"Flag dollar tightening",
			"Unavailable" if dollar is None else "Active" if dollar > 20 else "Inactive",
		],
		[
			"Missing/stale data or unvalidated coefficients",
			"Require human review; no automatic orders",
			"Always applies",
		],
	]
	hierarchy = [
		[
			"1",
			"Data validity and stress guardrails",
			"Override narrative; no numerical renormalization",
		],
		[
			"2",
			"Sector factor model",
			"Rates 18; curve 12; inflation 14; volatility 10; credit 12; legacy style 8",
		],
		["3", "Sector momentum", "Six-month return clipped at ±20%; contribution ±22"],
		[
			"4",
			"Risk and FX confirmation",
			"Separate risk flags; do not secretly change sector coefficients",
		],
	]
	return _section(
		"playbook",
		f"{stance}. Favor/neutral/avoid are research preferences, not trade orders. Scenario matrix reruns the actual sector model at ±1 rate/volatility/credit states, preserving current curve/inflation and setting momentum neutral. Disagreement is disclosed instead of hidden in a confidence percentage.",
		status="ready" if risk and risk_fx is not None and dollar is not None else "partial",
		metrics=[
			_metric("Current stance", stance),
			_metric("Ranking separation strength", strength, "score"),
			_metric("USD confirmation", dollar, "score"),
			_metric("Risk FX confirmation", risk_fx, "score"),
		],
		tables=[
			_table("Current preferences", ["Preference", "Sectors"], preferences),
			_table(
				"Conditional regime matrix",
				["Rates", "Volatility", "Credit", "Favor", "Avoid"],
				matrix,
			),
			_table(
				"Change / invalidation triggers",
				["Condition", "Research action", "Current state"],
				triggers,
			),
			_table("Signal hierarchy and guardrails", ["Priority", "Signal", "Rule"], hierarchy),
		],
	)


def _analogue_features(data: _Inputs, index: int) -> list[float] | None:
	arrays = [
		data.change("SPY_TR", 20),
		data.values("VIXCLS"),
		data.values("BAMLH0A0HYM2"),
		data.curve,
		data.values("DFII10"),
		data.change("UUP_TR", 20),
	]
	features = [_zscore(values[index], values[max(0, index - 252) : index]) for values in arrays]
	return (
		[_clip(value, 5) for value in features]
		if all(value is not None for value in features)
		else None
	)


def _analogue_candidates(data: _Inputs) -> list[dict]:
	current = _analogue_features(data, data.index)
	if current is None:
		return []
	candidates = []
	# Candidate selection reads only states, never their forward outcomes.
	for index in range(80, data.index - 20):
		features = _analogue_features(data, index)
		if features is None:
			continue
		distance = math.sqrt(
			fmean((left - right) ** 2 for left, right in zip(current, features, strict=True))
		)
		candidates.append(
			{"index": index, "distance": distance, "similarity": 100 / (1 + distance)}
		)
	candidates.sort(key=lambda item: (item["distance"], item["index"]))
	selected = []
	for item in candidates:
		if all(abs(item["index"] - prior["index"]) > 20 for prior in selected):
			selected.append(item)
			if len(selected) == 8:
				break
	return selected


def _analogues(data: _Inputs) -> dict:
	selected = _analogue_candidates(data)
	rows, paths, outcomes = [], [], []
	for item in selected:
		index = item["index"]
		forward = [data.delta(f"{symbol}_TR", 20, index + 20) for symbol in ("SPY", "GLD", "TLT")]
		if forward[0] is not None:
			outcomes.append(forward[0] * 100)
		rows.append(
			[
				str(data.sessions[index]),
				item["similarity"],
				item["distance"],
				*[v * 100 if v is not None else None for v in forward],
				str(data.sessions[index + 20]),
			]
		)
		paths.append(
			(
				str(data.sessions[index]),
				[
					(
						f"D{offset}",
						None
						if (
							value := _ratio(
								data.at("SPY_TR", index + offset), data.at("SPY_TR", index)
							)
						)
						is None
						else (value - 1) * 100,
					)
					for offset in range(21)
				],
			)
		)
	metrics = [
		_metric("Nonoverlapping matches", len(selected), "count"),
		_metric("Complete SPY outcomes", len(outcomes), "count"),
		_metric(
			"Matched mean forward SPY return", fmean(outcomes) if outcomes else None, "percent"
		),
		_metric(
			"Matched median forward SPY return", median(outcomes) if outcomes else None, "percent"
		),
		_metric(
			"Matched positive SPY outcomes",
			100 * sum(v > 0 for v in outcomes) / len(outcomes) if outcomes else None,
			"percent",
		),
	]
	charts = [
		_chart("Historical matches: subsequent SPY total return", "percent", paths),
		_chart(
			"Historical match similarity",
			"score",
			[
				(
					"Similarity",
					[
						(str(data.sessions[item["index"]]), item["similarity"])
						for item in sorted(selected, key=lambda item: item["index"])
					],
				)
			],
		),
	]
	current_features = _analogue_features(data, data.index)
	nearest_features = _analogue_features(data, selected[0]["index"]) if selected else None
	comparison = [
		[
			label,
			current_features[i] if current_features else None,
			nearest_features[i] if nearest_features else None,
			_difference(current_features[i], nearest_features[i])
			if current_features and nearest_features
			else None,
		]
		for i, label in enumerate(
			(
				"SPY 20D momentum",
				"VIX",
				"High-yield spread",
				"2s10s curve",
				"10Y real yield",
				"USD 20D momentum",
			)
		)
	]
	return _section(
		"analogues",
		"Up to eight nearest historical states, using equity momentum, volatility, credit, curve, real yields and USD momentum. Every endpoint is normalized using only its preceding observations. Matches are separated by more than 20 sessions; the most recent 20 sessions are excluded. Forward 20-session outcomes are computed only after selection, and incomplete outcomes stay null. Similarity is a distance transform, not a forecast probability; small matched samples are descriptive.",
		status="ready" if selected and outcomes else "unavailable",
		metrics=metrics,
		tables=[
			_table(
				"Nearest states and subsequent total returns",
				[
					"Match date",
					"Similarity (0–100)",
					"RMS distance",
					"SPY +20D (%)",
					"GLD +20D (%)",
					"TLT +20D (%)",
					"Outcome date",
				],
				rows,
			),
			_table(
				"What matched: standardized current versus nearest state",
				["Feature", "Current z (clipped ±5)", "Nearest historical z", "Difference"],
				comparison,
			),
		],
		charts=charts,
	)


def market_analytics(dataset: Dataset, now: datetime | None = None) -> dict[str, Any]:
	"""Return all V4 research families as transparent calculated sections."""
	now = now or datetime.now(UTC)
	if now.tzinfo is None or now.utcoffset() is None:
		raise ValueError("Analytics time must include a timezone")
	data = _Inputs(dataset, now.astimezone(UTC))
	if not data.valid or data.index < 1:
		return {
			"ok": False,
			"status": "unavailable",
			"dataset_id": dataset.dataset_id,
			"as_of": str(dataset.as_of),
			"model_version": ANALYTICS_VERSION,
			"sections": {
				key: _section(
					key,
					"Snapshot is not yet available, the calendar does not cover the publication cutoff, or fewer than two completed sessions are supplied.",
					status="unavailable",
				)
				for key in TITLES
			},
		}
	changes, anomalies = _changes_and_anomalies(data)
	sectors, ranked, state = _sectors(data)
	sections = {
		"risk": _risk(data),
		"changes": changes,
		"anomalies": anomalies,
		"correlations": _correlations(data),
		"rates": _rates(data),
		"volatility": _volatility(data),
		"fx": _fx(data),
		"sectors": sectors,
		"playbook": _playbook(data, ranked, state),
		"analogues": _analogues(data),
	}
	stale = data.sessions[-1] < data.expected
	for section in sections.values():
		if stale:
			section["status"] = "stale"
			section["summary"] = (
				f"STALE SNAPSHOT: observations end {data.sessions[-1]}; expected {data.expected}. "
				+ section["summary"]
			)
	status = (
		"stale"
		if stale
		else "ready"
		if all(section["status"] == "ready" for section in sections.values())
		else "partial"
		if any(section["status"] != "unavailable" for section in sections.values())
		else "unavailable"
	)
	return {
		"ok": status in {"ready", "partial"},
		"status": status,
		"dataset_id": dataset.dataset_id,
		"as_of": str(data.sessions[-1]),
		"model_version": ANALYTICS_VERSION,
		"sector_model_version": MODEL_VERSION,
		"sections": sections,
		"input_issues": data.errors,
		"inputs": [
			{
				"id": name,
				"source": dataset.series[name].source if name in dataset.series else None,
				"observation_date": str(data.observation_dates[name][-1])
				if data.observation_dates[name][-1]
				else None,
				"status": "ready" if values[-1] is not None else "unavailable",
				"reason": data.errors.get(name),
			}
			for name, values in sorted(data.arrays.items())
		],
		"assumptions": [
			"Explicit research heuristics; no calibrated probabilities or automatic trade instructions.",
			"Percentage values use percentage points (5 means 5%); missing inputs remain null.",
			"Historical states use releases available by their own New York end-of-day cutoff.",
		],
	}
