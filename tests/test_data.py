"""Boundary and resource tests use only in-memory/local synthetic observations."""

import asyncio
import json
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from pydantic import ValidationError

from radar.data import (
	DataError,
	Dataset,
	DatasetStore,
	Observation,
	dataset_content_id,
	exchange_sessions,
	parse_dataset,
)
from scripts.publish_dataset import publish_dataset


def raw_dataset():
	return {
		"schema_version": 1,
		"as_of": "2025-01-03",
		"generated_at": "2025-01-03T23:00:00Z",
		"calendar": ["2025-01-02", "2025-01-03"],
		"series": {
			"SPY": {
				"id": "SPY",
				"source": "synthetic test only",
				"unit": "USD",
				"currency": "USD",
				"price_basis": "close",
				"observations": [
					{"date": "2025-01-03", "value": 100, "available_at": "2025-01-03T22:00:00Z"}
				],
			}
		},
	}


def encoded_dataset(raw=None):
	raw = raw or raw_dataset()
	raw["dataset_id"] = dataset_content_id(raw)
	return json.dumps(raw).encode()


@pytest.mark.parametrize(
	"value",
	[
		None,
		"",
		" ",
		".",
		"NA",
		"NaN",
		"null",
		True,
		False,
		float("nan"),
		float("inf"),
		-float("inf"),
		"100",
	],
)
def test_raw_missing_and_nonfinite_values_rejected(value):
	with pytest.raises(ValidationError):
		Observation(date="2025-01-03", value=value, available_at="2025-01-03T22:00:00Z")


def test_zero_rate_allowed_and_zero_price_rejected():
	raw = raw_dataset()
	series = raw["series"]["SPY"]
	series["price_basis"], series["unit"] = "rate", "percent"
	series["observations"][0]["value"] = 0
	assert parse_dataset(encoded_dataset(raw)).series["SPY"].observations[0].value == 0
	series["price_basis"], series["unit"] = "close", "USD"
	with pytest.raises(ValidationError):
		encoded_dataset(raw)


@pytest.mark.parametrize(
	"key,value",
	[
		("source", ""),
		("source", "test\nvalue"),
		("unit", "bps"),
		("currency", "usd"),
		("id", "OTHER"),
		("price_basis", "adjusted"),
	],
)
def test_invalid_metadata_rejected(key, value):
	raw = raw_dataset()
	raw["series"]["SPY"][key] = value
	with pytest.raises((ValidationError, DataError)):
		parse_dataset(encoded_dataset(raw))


def test_content_id_is_stable_and_content_is_immutable():
	dataset = parse_dataset(encoded_dataset())
	assert dataset_content_id(dataset) == dataset.dataset_id
	assert parse_dataset(dataset.model_dump_json().encode()).dataset_id == dataset.dataset_id
	with pytest.raises(TypeError):
		dataset.series["OTHER"] = dataset.series["SPY"]
	with pytest.raises(ValidationError):
		dataset.series["SPY"].observations[0].value = 1
	raw = json.loads(encoded_dataset())
	raw["series"]["SPY"]["observations"][0]["value"] = 101
	with pytest.raises(DataError, match="validation"):
		parse_dataset(json.dumps(raw).encode())


def test_duplicate_json_and_calendar_holes_rejected():
	with pytest.raises(DataError):
		parse_dataset(b'{"a":1,"a":2}')
	raw = raw_dataset()
	raw["calendar"] = ["2025-01-02", "2025-01-06"]
	with pytest.raises(DataError):
		parse_dataset(encoded_dataset(raw))
	assert date(2025, 1, 1) not in exchange_sessions(date(2024, 12, 31), date(2025, 1, 3))
	assert exchange_sessions(date(2025, 1, 3), date(2025, 1, 3)) == (date(2025, 1, 3),)


def test_metadata_and_observation_budgets_are_checked_before_expansion():
	raw = json.loads(encoded_dataset())
	series = raw["series"]["SPY"]
	raw["series"] = {f"SERIES{index}": series for index in range(81)}
	with pytest.raises(ValidationError, match="between 1 and 80"):
		Dataset.model_validate(raw)
	raw["series"] = {
		f"SERIES{index}": {**series, "observations": series["observations"] * 30_000}
		for index in range(9)
	}
	with pytest.raises(ValidationError, match="budget exceeded"):
		Dataset.model_validate(raw)
	with pytest.raises(DataError) as error:
		parse_dataset(encoded_dataset(), max_bytes=2)
	assert error.value.code == "dataset_too_large"


def test_availability_timezone_revisions_and_future_are_validated():
	with pytest.raises(ValidationError):
		Observation(date="2025-01-03", value=100, available_at="2025-01-03T22:00:00")
	with pytest.raises(ValidationError):
		Observation(date="2025-01-03", value=100, available_at="2025-01-02T22:00:00Z")
	raw = raw_dataset()
	rows = raw["series"]["SPY"]["observations"]
	rows.append({**rows[0], "value": 101, "available_at": "2025-01-03T22:30:00Z"})
	assert len(parse_dataset(encoded_dataset(raw)).series["SPY"].observations) == 2
	rows.append({**rows[0], "available_at": "2025-01-04T22:00:00Z"})
	with pytest.raises(DataError):
		parse_dataset(encoded_dataset(raw))


async def test_load_coalescing_cache_and_no_stale_failure_success():
	calls = 0
	fail = False

	async def handler(request):
		nonlocal calls
		calls += 1
		await asyncio.sleep(0.01)
		return httpx.Response(503 if fail else 200, content=encoded_dataset())

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(url="https://datasets.example/radar.json", client=client, retries=0)
		results = await asyncio.gather(*(store.get() for _ in range(10)))
		assert calls == 1
		assert all(item is results[0] for item in results)
		await store.get()
		assert calls == 1
		store._expires_at = 0
		fail = True
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_upstream_unavailable"
		await store.aclose()


async def test_transient_retry_and_byte_limit():
	calls = 0

	async def handler(request):
		nonlocal calls
		calls += 1
		return (
			httpx.Response(429, headers={"Retry-After": "0"})
			if calls == 1
			else httpx.Response(200, content=encoded_dataset())
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(url="https://datasets.example/radar.json", client=client)
		await store.get()
		assert calls == 2
		await store.aclose()

		store = DatasetStore(url="https://datasets.example/radar.json", client=client, max_bytes=10)
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_too_large"
		await store.aclose()


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "gzip, identity"])
async def test_compressed_response_rejected_before_reading_or_decompression(encoding):
	class UnreadBody(httpx.AsyncByteStream):
		def __init__(self):
			self.read = False
			self.closed = False

		async def __aiter__(self):
			self.read = True
			yield b"body must never be read or decompressed"

		async def aclose(self):
			self.closed = True

	body = UnreadBody()

	def handler(request):
		assert request.headers["Accept-Encoding"] == "identity"
		return httpx.Response(200, headers={"Content-Encoding": encoding}, stream=body)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(url="https://datasets.example/radar.json", client=client)
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_encoding_unsupported"
		assert body.read is False
		assert body.closed is True
		await store.aclose()


async def test_deadline_cancels_underlying_request_and_releases_store():
	cancelled = asyncio.Event()

	async def handler(request):
		try:
			await asyncio.sleep(10)
		finally:
			cancelled.set()

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(
			url="https://datasets.example/radar.json", client=client, deadline_seconds=0.02
		)
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_timeout"
		assert cancelled.is_set()
		await store.aclose()


async def test_one_cancelled_waiter_does_not_cancel_other_consumers():
	started = asyncio.Event()
	finish = asyncio.Event()

	async def handler(request):
		started.set()
		await finish.wait()
		return httpx.Response(200, content=encoded_dataset())

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(url="https://datasets.example/radar.json", client=client)
		first, second = asyncio.create_task(store.get()), asyncio.create_task(store.get())
		await started.wait()
		first.cancel()
		with pytest.raises(asyncio.CancelledError):
			await first
		finish.set()
		assert (await second).dataset_id.startswith("sha256:")
		await store.aclose()


async def test_last_cancelled_waiter_cancels_fetch():
	started, cancelled = asyncio.Event(), asyncio.Event()

	async def handler(request):
		started.set()
		try:
			await asyncio.sleep(10)
		finally:
			cancelled.set()

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(url="https://datasets.example/radar.json", client=client)
		task = asyncio.create_task(store.get())
		await started.wait()
		task.cancel()
		with pytest.raises(asyncio.CancelledError):
			await task
		assert cancelled.is_set()
		await store.aclose()


async def test_validation_deadline_retains_worker_and_bounds_replacement(monkeypatch):
	import radar.data as data_module

	original = data_module.parse_dataset

	def slow_parse(payload, *, max_bytes):
		time.sleep(0.08)
		return original(payload, max_bytes=max_bytes)

	monkeypatch.setattr(data_module, "parse_dataset", slow_parse)
	async with httpx.AsyncClient(
		transport=httpx.MockTransport(
			lambda request: httpx.Response(200, content=encoded_dataset())
		)
	) as client:
		store = DatasetStore(
			url="https://datasets.example/radar.json", client=client, deadline_seconds=0.02
		)
		started = time.monotonic()
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_timeout"
		assert time.monotonic() - started < 0.07
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_busy"
		await store.aclose()
		assert store._validation_task.done()


async def test_private_distribution_auth_and_http_date_retry_budget():
	calls = []

	def handler(request):
		calls.append(request)
		assert request.headers["Authorization"] == "Bearer test-secret-only"
		return httpx.Response(
			429,
			headers={
				"Retry-After": format_datetime(
					datetime.now(UTC) + timedelta(minutes=1), usegmt=True
				)
			},
		)

	async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
		store = DatasetStore(
			url="https://datasets.example/radar.json", token="test-secret-only", client=client
		)
		with pytest.raises(DataError) as error:
			await store.get()
		assert error.value.code == "dataset_retry_later"
		assert "test-secret-only" not in str(error.value)
		assert len(calls) == 1
		await store.aclose()


async def test_local_loading_configuration_and_atomic_publication(tmp_path, monkeypatch):
	monkeypatch.delenv("RADAR_DATASET_PATH", raising=False)
	monkeypatch.delenv("RADAR_DATASET_URL", raising=False)
	with pytest.raises(ValueError):
		DatasetStore(url="http://example.test/data")
	with pytest.raises(ValueError):
		DatasetStore(path="x", url="https://example.test/data")
	with pytest.raises(DataError) as error:
		await DatasetStore().get()
	assert error.value.code == "dataset_not_configured"
	source, target = tmp_path / "input.json", tmp_path / "published" / "current.json"
	source.write_text(json.dumps(raw_dataset()))
	with pytest.raises(DataError) as error:
		publish_dataset(source, target)
	assert error.value.code == "incomplete_dataset"
	assert not target.exists()
	first = publish_dataset(source, target, allow_partial=True)
	store = DatasetStore(path=target)
	assert (await store.get()).dataset_id == first.dataset_id
	await store.aclose()
	assert len(list((target.parent / "versions").glob("*.json"))) == 1
	source.write_text("invalid")
	with pytest.raises(DataError):
		publish_dataset(source, target, allow_partial=True)
	assert parse_dataset(target.read_bytes()).dataset_id == first.dataset_id
