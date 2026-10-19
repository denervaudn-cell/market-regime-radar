"""Explicit mock provenance and deterministic inputs share the real data boundary."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from radar.data import Dataset, dataset_content_id, parse_dataset
from radar.market import market_snapshot
from radar.mock import MockDatasetStore, generate_mock_dataset, preview_session


@pytest.fixture(scope="module")
def mock_dataset():
	return generate_mock_dataset(date(2021, 4, 15), seed=91)


def test_mock_inputs_are_reproducible_validated_and_explicit(mock_dataset):
	repeated = generate_mock_dataset(date(2021, 4, 15), seed=91)
	assert repeated.dataset_id == mock_dataset.dataset_id
	assert mock_dataset.source.kind == "mock"
	assert mock_dataset.source.seed == 91
	assert len(mock_dataset.series) == 62
	assert all(series.source.startswith("MOCK ") for series in mock_dataset.series.values())
	assert (
		parse_dataset(mock_dataset.model_dump_json().encode()).dataset_id == mock_dataset.dataset_id
	)
	assert market_snapshot(mock_dataset, datetime(2021, 4, 15, 21, tzinfo=UTC))["status"] == "ready"
	changed = generate_mock_dataset(date(2021, 4, 15), seed=92)
	assert changed.dataset_id != mock_dataset.dataset_id
	assert (
		changed.series["SPY_TR"].observations[-1].value
		!= mock_dataset.series["SPY_TR"].observations[-1].value
	)


def test_mock_crosses_and_price_return_conventions(mock_dataset):
	values = {
		symbol: series.observations[-1].value for symbol, series in mock_dataset.series.items()
	}
	assert values["AUDJPY"] == pytest.approx(values["AUDUSD"] * values["USDJPY"], rel=1e-7)
	assert values["DGS10"] == pytest.approx(values["DFII10"] + values["T10YIE"], abs=1e-7)
	assert values["T5YIFR"] == pytest.approx(
		100 * ((1 + values["T10YIE"] / 100) ** 2 / (1 + values["T5YIE"] / 100) - 1), abs=1e-7
	)
	spy = mock_dataset.series["SPY"].observations
	returns = mock_dataset.series["SPY_TR"].observations
	assert spy[-1].value / spy[0].value < returns[-1].value / returns[0].value
	assert any(current.value < previous.value for previous, current in zip(returns, returns[1:]))
	assert any(current.value > previous.value for previous, current in zip(returns, returns[1:]))


def test_mock_origin_is_hashed_not_a_display_only_flag(mock_dataset):
	payload = mock_dataset.model_dump(mode="json")
	payload["source"] = {"kind": "real", "label": "Changed source", "seed": None}
	assert dataset_content_id(payload) != mock_dataset.dataset_id
	with pytest.raises(ValidationError, match="immutable identifier"):
		Dataset.model_validate(payload)
	payload["source"]["seed"] = 91
	with pytest.raises(ValidationError, match="generator seed"):
		dataset_content_id(payload)


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.5, "12"])
def test_mock_seed_rejects_ambiguous_values(seed):
	with pytest.raises(ValueError, match="seed"):
		generate_mock_dataset(date(2021, 4, 15), seed=seed)


def test_preview_cutoff_respects_weekends_and_publication_time():
	assert preview_session(datetime(2026, 10, 19, 20, 29, tzinfo=UTC)) == date(2026, 10, 16)
	assert preview_session(datetime(2026, 10, 19, 20, 30, tzinfo=UTC)) == date(2026, 10, 19)
	assert preview_session(datetime(2026, 10, 18, 22, tzinfo=UTC)) == date(2026, 10, 16)


async def test_mock_generation_is_shared_and_shutdown_drains(monkeypatch, mock_dataset):
	import threading

	gate, calls = threading.Event(), []

	def generate(*args, **kwargs):
		calls.append(args)
		gate.wait(2)
		return mock_dataset

	monkeypatch.setattr("radar.mock.generate_mock_dataset", generate)
	monkeypatch.setattr("radar.mock.preview_session", lambda: mock_dataset.as_of)
	store = MockDatasetStore()
	first, second = asyncio.create_task(store.get()), asyncio.create_task(store.get())
	await asyncio.sleep(0.03)
	first.cancel()
	with pytest.raises(asyncio.CancelledError):
		await first
	gate.set()
	assert await second is mock_dataset
	assert await store.get() is mock_dataset
	assert len(calls) == 1
	await store.aclose()
	with pytest.raises(Exception, match="shutting down"):
		await store.get()
