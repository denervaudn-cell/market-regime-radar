"""Deterministic synthetic inputs for an explicitly selected local research preview.

Only observations are generated here. All displayed analytics are calculated by
the same production engine that consumes real data_mesh snapshots.
"""

from __future__ import annotations

import asyncio
import math
import random
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from radar.data import DataError, Dataset, dataset_content_id, exchange_sessions

NY = ZoneInfo("America/New_York")
START = date(2018, 6, 19)
DEFAULT_SEED = 8042
ETF_BETAS = {
	"SPY": (1.0, 0.0, 0.0),
	"QQQ": (1.15, -0.4, -0.1),
	"XLB": (1.05, 0.2, 0.5),
	"XLC": (1.05, -0.2, 0.0),
	"XLE": (0.8, 0.1, 1.2),
	"XLF": (1.05, 0.6, 0.1),
	"XLI": (1.0, 0.2, 0.3),
	"XLK": (1.2, -0.6, -0.1),
	"XLP": (0.55, -0.1, -0.1),
	"XLRE": (0.7, -0.8, 0.0),
	"XLU": (0.45, -0.9, -0.1),
	"XLV": (0.65, -0.1, 0.0),
	"XLY": (1.1, -0.2, -0.2),
	"GLD": (0.05, -0.4, 0.2),
	"USO": (0.25, 0.1, 1.6),
	"UUP": (-0.1, 0.2, -0.15),
	"TLT": (-0.1, -1.8, -0.1),
	"CPER": (0.4, 0.1, 1.2),
}
FX_INITIAL = {
	"EURUSD": 1.12,
	"USDJPY": 112.0,
	"USDCHF": 0.97,
	"GBPUSD": 1.3,
	"AUDUSD": 0.72,
	"USDCAD": 1.3,
	"USDCNH": 6.7,
}


def preview_session(now: datetime | None = None) -> date:
	"""Match the dashboard's conservative 16:30 NY completed-session cutoff."""
	now = now or datetime.now(UTC)
	if now.tzinfo is None:
		raise ValueError("Mock preview time must include a timezone")
	local = now.astimezone(NY)
	days = exchange_sessions(local.date() - timedelta(days=14), local.date())
	return [day for day in days if day < local.date() or local.time() >= time(16, 30)][-1]


def generate_mock_dataset(as_of: date | None = None, *, seed: int = DEFAULT_SEED) -> Dataset:
	"""Generate a reproducible, correlated 62-series fixture with changing regimes.

	No observation purports to be a historical market quote. Model states, prices,
	FX and term structures vary smoothly with independent seeded shocks so charts,
	regime changes, sensitivities and adverse paths exercise real calculations.
	"""
	as_of = as_of or preview_session()
	if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**32:
		raise ValueError("Mock seed must be an integer from 0 through 4294967295")
	if as_of < date(2020, 1, 1) or as_of > preview_session():
		raise ValueError("Mock cutoff must be a completed session from 2020 onward")
	calendar = exchange_sessions(START, as_of + timedelta(days=40))
	sessions = [day for day in calendar if day <= as_of]
	as_of = sessions[-1]
	rng = random.Random(seed)
	series: dict[str, dict] = {}
	levels = {symbol: 100.0 + index * 11 for index, symbol in enumerate(ETF_BETAS)}
	tr = {symbol: 100.0 for symbol in ETF_BETAS}
	fx = FX_INITIAL.copy()
	previous_yield = 3.0

	def add(symbol: str, value: float, day: date, basis: str, unit: str, currency=None):
		if symbol not in series:
			series[symbol] = {
				"id": symbol,
				"source": f"MOCK seeded generator v1 / {symbol}",
				"price_basis": basis,
				"unit": unit,
				"currency": currency,
				"observations": [],
			}
		series[symbol]["observations"].append(
			{
				"date": day.isoformat(),
				"value": round(value, 8),
				"available_at": datetime.combine(day, time(16, 15), NY).isoformat(),
			}
		)

	for index, day in enumerate(sessions):
		cycle = math.sin(index / 95)
		inflation = 2.15 + 0.55 * math.sin(index / 160) + rng.gauss(0, 0.025)
		inflation5 = inflation + 0.16 * math.sin(index / 130)
		real_yield = 1.0 + 0.85 * math.sin(index / 230) + rng.gauss(0, 0.025)
		yield10 = real_yield + inflation
		slope = 0.45 + 0.8 * math.sin(index / 170 + 0.5)
		yield2 = yield10 - slope
		yield5 = 0.48 * yield2 + 0.52 * yield10 + 0.08 * math.sin(index / 80)
		yield30 = yield10 + 0.25 + 0.2 * math.sin(index / 145)
		stress = max(0.0, -cycle)
		vix = 15.5 + stress * 12 + 2.5 * math.sin(index / 17) + abs(rng.gauss(0, 0.9))
		credit = 3.1 + stress * 2.5 + 0.3 * math.sin(index / 42) + abs(rng.gauss(0, 0.06))
		macro = {
			"DGS2": yield2,
			"DGS5": yield5,
			"DGS10": yield10,
			"DGS30": yield30,
			"DFII10": real_yield,
			"T10YIE": inflation,
			"T5YIE": inflation5,
			"T5YIFR": 100 * ((1 + inflation / 100) ** 2 / (1 + inflation5 / 100) - 1),
			"BAMLH0A0HYM2": credit,
			"DFF": max(0.1, yield2 - 0.35),
		}
		for symbol, value in macro.items():
			add(symbol, value, day, "rate", "percent")
		vols = {
			"VIXCLS": vix,
			"VIX9D": vix * (0.82 + stress * 0.28),
			"VIX3M": vix * (1.12 - stress * 0.16),
			"VIX6M": vix * (1.2 - stress * 0.22),
			"VIX1Y": vix * (1.27 - stress * 0.27),
			"VVIX": 75 + vix * 1.5 + rng.gauss(0, 1),
			"SKEW": 118 + 10 * math.sin(index / 60) + rng.gauss(0, 2),
			"MOVE": 65 + stress * 35 + 10 * math.sin(index / 37) + abs(rng.gauss(0, 2)),
		}
		for symbol, value in vols.items():
			add(symbol, value, day, "index", "index")
		equity_shock = rng.gauss(0, vix / 100 / math.sqrt(252))
		rate_shock = (yield10 - previous_yield) / 100
		commodity_shock = rng.gauss(0, 0.01) + 0.0003 * math.sin(index / 110)
		for symbol, (beta, rate_beta, commodity_beta) in ETF_BETAS.items():
			ret = 0.00012 + 0.00022 * cycle + beta * equity_shock
			ret += rate_beta * rate_shock * 4 + commodity_beta * commodity_shock
			ret += rng.gauss(0, 0.0018)
			ret = max(-0.12, min(0.12, ret))
			tr[symbol] *= math.exp(ret)
			levels[symbol] *= math.exp(ret - 0.00006)
			add(f"{symbol}_TR", tr[symbol], day, "total_return_net", "index", "USD")
			add(symbol, levels[symbol], day, "close", "USD", "USD")
		usd_shock = -0.14 * equity_shock + rng.gauss(0, 0.002)
		for symbol in fx:
			direction = -1 if symbol.endswith("USD") else 1
			risk = 0.12 * equity_shock if symbol in {"AUDUSD", "GBPUSD"} else 0.0
			fx[symbol] *= math.exp(direction * usd_shock + risk + rng.gauss(0, 0.0007))
			add(symbol, fx[symbol], day, "fx", f"{symbol[3:]}/{symbol[:3]}")
		add("AUDJPY", fx["AUDUSD"] * fx["USDJPY"], day, "fx", "JPY/AUD")
		previous_yield = yield10

	payload = {
		"schema_version": 1,
		"source": {
			"kind": "mock",
			"label": "Synthetic market inputs · seeded preview v1",
			"seed": seed,
		},
		"generated_at": datetime.combine(as_of, time(16, 30), NY).isoformat(),
		"as_of": as_of.isoformat(),
		"calendar": [day.isoformat() for day in calendar],
		"series": series,
	}
	payload["dataset_id"] = dataset_content_id(payload)
	return Dataset.model_validate(payload)


class MockDatasetStore:
	"""One owned generator job, refreshed only when the completed session changes."""

	def __init__(self, seed: int = DEFAULT_SEED) -> None:
		self.seed = seed
		self._dataset: Dataset | None = None
		self._task: asyncio.Task | None = None
		self._closed = False

	async def get(self) -> Dataset:
		if self._closed:
			raise DataError("dataset_store_closed", "The mock data service is shutting down")
		cutoff = preview_session()
		if self._dataset is not None and self._dataset.as_of == cutoff:
			return self._dataset
		if self._task is None or self._task.done():
			self._task = asyncio.create_task(
				asyncio.to_thread(generate_mock_dataset, cutoff, seed=self.seed)
			)
			self._task.add_done_callback(
				lambda task: None if task.cancelled() else task.exception()
			)
		try:
			self._dataset = await asyncio.wait_for(asyncio.shield(self._task), 15)
		except TimeoutError as exc:
			raise DataError("dataset_timeout", "Mock generation exceeded its time budget") from exc
		return self._dataset

	async def aclose(self) -> None:
		self._closed = True
		if self._task is not None:
			await asyncio.gather(self._task, return_exceptions=True)
		self._dataset = None
