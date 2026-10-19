"""Daily, date-aligned market analytics with explicit evidence and freshness."""

from __future__ import annotations

import math
import statistics
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from radar.data import Dataset, Observation, Series

ASSETS = {
	"SPY": "US large-cap equity ETF",
	"QQQ": "Nasdaq-100 equity ETF",
	"XLF": "Financials ETF",
	"XLK": "Technology ETF",
	"XLE": "Energy ETF",
	"GLD": "Gold ETF",
	"USO": "Oil futures ETF",
	"UUP": "US dollar futures ETF",
}
RATES = {"DGS2": "2Y", "DGS5": "5Y", "DGS10": "10Y", "DGS30": "30Y"}
MIN_CORRELATION_SAMPLES = 15
_NY = ZoneInfo("America/New_York")


def _latest_versions(series: Series | None, now: datetime) -> dict[date, Observation]:
	versions = {}
	if series is not None:
		for row in series.observations:
			if row.available_at <= now and row.date <= now.date():
				versions[row.date] = row
	return versions


def _status(
	series: Series | None,
	rows: dict[date, Observation],
	expected: date | None,
	*,
	macro: bool = False,
) -> tuple[str, str | None]:
	if series is None or not rows:
		return "unavailable", "Required observations are absent or not yet available"
	if expected is None:
		return "unavailable", "The exchange calendar does not cover the current publication cutoff"
	latest = max(rows)
	if latest > expected:
		return "unavailable", "Observation is after the latest completed exchange session"
	if latest < expected and (not macro or (expected - latest).days > 3):
		return "stale", "The latest observation is older than the declared freshness budget"
	return "ready", None


def _returns(
	rows: dict[date, Observation], calendar: tuple[date, ...], expected: date | None
) -> dict[tuple[date, date], float]:
	"""Compute only consecutive exchange-session returns with matching endpoints."""
	result = {}
	for prior, current in zip(calendar, calendar[1:]):
		if expected is not None and current > expected:
			break
		if prior in rows and current in rows:
			result[(prior, current)] = rows[current].value / rows[prior].value - 1
	return result


def _correlation(left: list[float], right: list[float]) -> float | None:
	if len(left) < MIN_CORRELATION_SAMPLES:
		return None
	mean_left, mean_right = statistics.fmean(left), statistics.fmean(right)
	left_ss = sum((value - mean_left) ** 2 for value in left)
	right_ss = sum((value - mean_right) ** 2 for value in right)
	if left_ss <= 1e-24 or right_ss <= 1e-24:
		return None
	value = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right)) / math.sqrt(
		left_ss * right_ss
	)
	return max(-1.0, min(1.0, value))


def market_snapshot(dataset: Dataset, now: datetime | None = None) -> dict[str, Any]:
	"""Publish real observations and derived daily measures, never fixture substitutes.

	The conservative publication cutoff is 16:30 America/New_York, including early
	close sessions. Macro observations allow at most three calendar days of lag.
	"""
	now = now or datetime.now(UTC)
	if now.tzinfo is None or now.utcoffset() is None:
		raise ValueError("Market time must include a timezone")
	now = now.astimezone(UTC)
	local = now.astimezone(_NY)
	eligible = [
		day
		for day in dataset.calendar
		if day < local.date() or (day == local.date() and local.time() >= time(16, 30))
	]
	calendar_valid = dataset.calendar[0] <= local.date() <= dataset.calendar[-1]
	expected = eligible[-1] if eligible and calendar_valid else None
	if dataset.generated_at > now or dataset.as_of > local.date():
		expected = None
	versions = {key: _latest_versions(series, now) for key, series in dataset.series.items()}
	metadata: list[dict[str, Any]] = []
	assets = []
	returns = {}
	statuses = []

	def evidence(
		key: str, *, basis: str, unit: str, macro: bool = False
	) -> tuple[Series | None, dict[date, Observation], str]:
		series = dataset.series.get(key)
		rows = versions.get(key, {})
		status, reason = _status(series, rows, expected, macro=macro)
		if series and (
			series.price_basis != basis
			or series.unit != unit
			or (
				basis in {"close", "total_return_net", "total_return_gross"}
				and series.currency != "USD"
			)
		):
			status, reason = (
				"unavailable",
				"The supplied price basis or units do not match this calculation",
			)
		latest = rows[max(rows)] if rows else None
		metadata.append(
			{
				"id": key,
				"source": series.source if series else None,
				"as_of": latest.date.isoformat() if latest else None,
				"available_at": latest.available_at.isoformat() if latest else None,
				"status": status,
				"reason": reason,
			}
		)
		return series, rows, status

	return_bases = {
		dataset.series[f"{symbol}_TR"].price_basis
		for symbol in ASSETS
		if f"{symbol}_TR" in dataset.series
		and dataset.series[f"{symbol}_TR"].price_basis in {"total_return_net", "total_return_gross"}
	}
	consistent_returns = len(return_bases) <= 1
	for symbol, label in ASSETS.items():
		series, rows, close_status = evidence(symbol, basis="close", unit="USD")
		return_id = f"{symbol}_TR"
		declared = dataset.series.get(return_id)
		basis = (
			declared.price_basis
			if declared and declared.price_basis in {"total_return_net", "total_return_gross"}
			else "total_return_net"
		)
		return_series, return_rows, return_status = evidence(return_id, basis=basis, unit="index")
		if not consistent_returns:
			return_status = "unavailable"
			metadata[-1]["status"] = "unavailable"
			metadata[-1]["reason"] = (
				"Market return histories must share one net/gross dividend convention"
			)
		status = (
			"unavailable"
			if "unavailable" in (close_status, return_status)
			else "stale"
			if "stale" in (close_status, return_status)
			else "ready"
		)
		statuses.append(status)
		intervals = (
			_returns(return_rows, dataset.calendar, expected) if return_status == "ready" else {}
		)
		returns[symbol] = intervals
		latest = rows[max(rows)] if rows else None
		return_latest = return_rows[max(return_rows)] if return_rows else None
		completed = [day for day in dataset.calendar if return_latest and day <= return_latest.date]
		change_1d = intervals.get((completed[-2], completed[-1])) if len(completed) >= 2 else None
		change_20d = None
		if (
			return_status == "ready"
			and len(completed) >= 21
			and all(day in return_rows for day in completed[-21:])
		):
			change_20d = return_rows[completed[-1]].value / return_rows[completed[-21]].value - 1
		return_history = list(intervals.values())[-261:]
		prior_returns = return_history[:-1]
		z_score = None
		percentile = None
		if change_1d is not None and len(prior_returns) >= 60:
			deviation = statistics.stdev(prior_returns)
			if deviation > 1e-12:
				z_score = (change_1d - statistics.fmean(prior_returns)) / deviation
			percentile = (
				100
				* (
					sum(value < change_1d for value in prior_returns)
					+ 0.5 * sum(value == change_1d for value in prior_returns)
				)
				/ len(prior_returns)
			)
		assets.append(
			{
				"symbol": symbol,
				"label": label,
				"latest": latest.value if latest else None,
				"change_1d": change_1d,
				"change_20d": change_20d,
				"z_1d": z_score,
				"percentile": percentile,
				"source": series.source if series else None,
				"as_of": latest.date.isoformat() if latest else None,
				"status": status,
				"price_basis": "close",
				"currency": "USD",
				"return_source": return_series.source if return_series else None,
				"return_as_of": return_latest.date.isoformat() if return_latest else None,
				"return_basis": basis if return_series else None,
				"quote_status": close_status,
				"return_status": return_status,
			}
		)
	rates = []
	macro_rows = {}
	macro_status = {}
	for key in [*RATES, "DFII10", "T10YIE", "VIXCLS", "BAMLH0A0HYM2"]:
		basis, unit = ("index", "index") if key == "VIXCLS" else ("rate", "percent")
		series, rows, status = evidence(key, basis=basis, unit=unit, macro=True)
		macro_rows[key], macro_status[key] = rows, status
		if key in RATES:
			latest = rows[max(rows)] if rows else None
			statuses.append(status)
			rates.append(
				{
					"tenor": RATES[key],
					"id": key,
					"value": latest.value if latest else None,
					"source": series.source if series else None,
					"as_of": latest.date.isoformat() if latest else None,
					"status": status,
					"unit": "percent",
				}
			)

	labels = list(ASSETS)
	matrix, samples = [], []
	cutoff_intervals = set(zip(dataset.calendar, dataset.calendar[1:]))
	if expected:
		cutoff_intervals = {pair for pair in cutoff_intervals if pair[1] <= expected}
	cutoff_intervals = set(sorted(cutoff_intervals)[-20:])
	for left in labels:
		values, counts = [], []
		for right in labels:
			pairs = sorted(returns[left].keys() & returns[right].keys() & cutoff_intervals)
			counts.append(len(pairs))
			values.append(
				_correlation(
					[returns[left][pair] for pair in pairs],
					[returns[right][pair] for pair in pairs],
				)
				if expected
				else None
			)
		matrix.append(values)
		samples.append(counts)
	correlation = {
		"labels": labels,
		"matrix": matrix,
		"sample_sizes": samples,
		"min_samples": MIN_CORRELATION_SAMPLES,
		"window_sessions": 20,
		"basis": "consecutive total-return-index returns with identical start and end dates",
	}

	spy = assets[0]
	factors = []
	if spy["status"] == "ready" and spy["change_20d"] is not None:
		factors.append(
			{
				"id": "SPY",
				"label": "20-session equity trend",
				"value": spy["change_20d"],
				"unit": "fraction",
				"source": spy["source"],
				"as_of": spy["as_of"],
				"status": "ready",
			}
		)
	for key, label in (("VIXCLS", "VIX close"), ("BAMLH0A0HYM2", "High-yield credit spread")):
		if macro_status[key] == "ready":
			row = macro_rows[key][max(macro_rows[key])]
			factors.append(
				{
					"id": key,
					"label": label,
					"value": row.value,
					"unit": dataset.series[key].unit,
					"source": dataset.series[key].source,
					"as_of": row.date.isoformat(),
					"status": "ready",
				}
			)
	risk_bias = {
		"label": "Model review required",
		"score": None,
		"status": "unavailable",
		"factors": factors,
		"explanation": "These are observed inputs, not a recommendation. The legacy risk-bias formula relied on placeholder stress values and has no approved interpretation or calibration. A live directional score remains unavailable pending model review.",
	}

	def item(key: str, label: str) -> dict[str, Any] | None:
		if macro_status.get(key) != "ready":
			return None
		row = macro_rows[key][max(macro_rows[key])]
		return {
			"label": label,
			"value": row.value,
			"unit": dataset.series[key].unit,
			"as_of": row.date.isoformat(),
			"source": dataset.series[key].source,
			"status": "ready",
		}

	yield_items = [
		entry
		for entry in [item("DFII10", "10Y real yield"), item("T10YIE", "10Y inflation breakeven")]
		if entry
	]
	if macro_status["DGS2"] == macro_status["DGS10"] == "ready":
		common = macro_rows["DGS2"].keys() & macro_rows["DGS10"].keys()
		if common:
			day = max(common)
			if expected and (expected - day).days <= 3:
				yield_items.append(
					{
						"label": "10Y minus 2Y Treasury slope",
						"value": macro_rows["DGS10"][day].value - macro_rows["DGS2"][day].value,
						"unit": "percentage_points",
						"as_of": day.isoformat(),
						"source": f"{dataset.series['DGS10'].source} / {dataset.series['DGS2'].source}",
						"status": "ready",
					}
				)
	vol_items = [entry for entry in [item("VIXCLS", "VIX close")] if entry]
	for key in ("VIX9D", "VIX3M", "VIX6M", "VIX1Y", "VVIX", "SKEW", "MOVE"):
		series, rows, status = evidence(key, basis="index", unit="index", macro=True)
		if status == "ready":
			row = rows[max(rows)]
			vol_items.append(
				{
					"label": key,
					"value": row.value,
					"unit": "index",
					"as_of": row.date.isoformat(),
					"source": series.source,
					"status": status,
				}
			)
	fx_items = []
	for key in ("EURUSD", "USDJPY", "USDCHF", "GBPUSD", "AUDUSD", "USDCAD", "USDCNH", "AUDJPY"):
		series, rows, status = evidence(key, basis="fx", unit=f"{key[3:]}/{key[:3]}")
		if status == "ready":
			row = rows[max(rows)]
			fx_items.append(
				{
					"label": key,
					"value": row.value,
					"unit": series.unit,
					"as_of": row.date.isoformat(),
					"source": series.source,
					"status": status,
				}
			)
	panels = {}
	for key, entries, reason in (
		(
			"yield_curve",
			yield_items,
			"Real yields, breakevens and matching curve observations are not available",
		),
		("volatility", vol_items, "Volatility inputs are not available"),
		("fx", fx_items, "Validated FX pairs have not been supplied"),
	):
		panels[key] = {
			"status": "ready" if entries else "unavailable",
			"items": entries,
			"reason": None if entries else reason,
		}
	panels["sector_ranking"] = {
		"status": "unavailable",
		"items": [],
		"reason": "Historical sector scores are published only within a completed backtest; no separate live recommendation model is enabled",
	}
	panels["robustness"] = {
		"status": "unavailable",
		"items": [],
		"reason": "Out-of-sample and parameter-sensitivity research has not been performed",
	}
	status = (
		"unavailable" if "unavailable" in statuses else "stale" if "stale" in statuses else "ready"
	)
	return {
		"ok": status == "ready",
		"status": status,
		"dataset_id": dataset.dataset_id,
		"as_of": dataset.as_of.isoformat(),
		"generated_at": dataset.generated_at.isoformat(),
		"assets": assets,
		"rates": rates,
		"correlation": correlation,
		"risk_bias": risk_bias,
		"panels": panels,
		"metadata": {
			"expected_session": expected.isoformat() if expected else None,
			"calendar_status": "ready" if expected else "out_of_range",
			"publication_cutoff": "16:30 America/New_York (conservative on early closes)",
			"macro_max_lag_calendar_days": 3,
			"series": metadata,
			"return_basis": next(iter(return_bases)) if len(return_bases) == 1 else "unavailable",
			"percentile_basis": "latest daily total return against prior 60–260 daily returns, midrank ties",
			"correlation_min_samples": MIN_CORRELATION_SAMPLES,
		},
	}
