"""Small synthetic reference histories, exclusively for offline financial tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

import exchange_calendars

from radar.data import Dataset, dataset_content_id
from radar.engine import MACRO, SECTORS


@lru_cache(maxsize=4)
def _payload(as_of: date) -> dict:
	calendar = exchange_calendars.get_calendar(
		"XNYS", start="2018-11-01", end=as_of + timedelta(days=40)
	)
	sessions = [item.date() for item in calendar.sessions]
	observed = [day for day in sessions if day <= as_of]
	series = {}
	for name in [*(f"{symbol}_TR" for symbol in (*SECTORS, "SPY")), *MACRO]:
		is_price = name.endswith("_TR")
		is_index = name == "VIXCLS"
		value = 100.0 if is_price else 20.0 if is_index else 0.0
		series[name] = {
			"id": name,
			"source": "SYNTHETIC TEST FIXTURE",
			"unit": "index" if is_price or is_index else "percent",
			"price_basis": "total_return_net" if is_price else "index" if is_index else "rate",
			"currency": "USD" if is_price else None,
			"observations": [
				{
					"date": str(day),
					"value": value,
					"available_at": datetime.combine(
						day, time(17), ZoneInfo("America/New_York")
					).isoformat(),
				}
				for day in observed
			],
		}
	return {
		"schema_version": 1,
		"generated_at": datetime.combine(as_of + timedelta(days=1), time(4), UTC).isoformat(),
		"as_of": str(as_of),
		"calendar": [str(day) for day in sessions],
		"series": series,
	}


def fixture_payload(as_of: date = date(2021, 4, 15)) -> dict:
	"""Return an independently mutable flat-market dataset payload."""
	return deepcopy(_payload(as_of))


def dataset_from_payload(payload: dict) -> Dataset:
	"""Recompute snapshot identity after an intentional test scenario edit."""
	payload["dataset_id"] = dataset_content_id(payload)
	return Dataset.model_validate(payload)


def flat_dataset(as_of: date = date(2021, 4, 15)) -> Dataset:
	"""Create an immutable complete test snapshot."""
	return dataset_from_payload(fixture_payload(as_of))
