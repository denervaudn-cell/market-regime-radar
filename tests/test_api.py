"""Routed HTTP checks: invalid requests never acquire data or silently select a mode."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from radar.app import ResultCache, WorkBudget, create_app
from radar.data import DataError


class Store:
	def __init__(self, failure=None):
		self.calls = 0
		self.closed = False
		self.failure = failure
		self.dataset = SimpleNamespace(dataset_id="test-version")

	async def get(self):
		self.calls += 1
		if self.failure:
			raise self.failure
		return self.dataset

	async def aclose(self):
		self.closed = True


@pytest.mark.parametrize(
	"query",
	[
		"start=2020-01-01&mode=unknown",
		"start=bad",
		"start=2020-02-30",
		"start=2020-01-01&start=2021-01-01",
		"start=2020-01-01&topN=2.5",
		"start=2020-01-01&cost_bps=Infinity",
		"start=2020-01-01&cost_bps=NaN",
		"start=2020-01-01&cost_bps=",
		"start=2020-01-01&short_borrow_bps=-1",
		"start=2020-01-01&costBps=1&cost_bps=2",
		"start=2020-01-01&rebalance=daily",
		"start=2020-01-01&top_n=6",
		"start=2020-01-01&top_n=3&topN=2",
		"start=2020-01-01&end=2019-01-01",
		"start=2008-01-01",
		"",
	],
)
def test_bad_parameters_fail_before_acquisition(query):
	store = Store()
	with TestClient(create_app(store)) as client:
		response = client.get("/api/backtest?" + query)
		assert response.status_code == 400
		assert response.json()["error"]["code"] == "invalid_parameters"
		assert response.headers["cache-control"] == "no-store"
		assert store.calls == 0
	assert store.closed


def test_zero_cost_and_mode_reach_one_engine_and_cache(monkeypatch):
	store, captured = Store(), []

	def calculate(dataset, params):
		captured.append(params)
		return {
			"ok": True,
			"dataset_id": dataset.dataset_id,
			"params": params.model_dump(mode="json"),
			"results": {"longonly3": {"strategy": "longonly3"}},
		}

	monkeypatch.setattr("radar.app.run_backtest", calculate)
	with TestClient(create_app(store)) as client:
		url = "/api/backtest?start=2020-01-01&mode=longonly3&cost_bps=0&shortBorrowBps=0"
		first, second = client.get(url), client.get(url)
		assert first.status_code == second.status_code == 200
		assert first.json() == second.json()
		assert len(captured) == 1
		assert captured[0].cost_bps == captured[0].short_borrow_bps == 0
		assert first.headers["x-request-id"] != second.headers["x-request-id"]


@pytest.mark.parametrize("path", ["/api/market", "/api/backtest", "/api/analytics", "/api/studies"])
def test_method_is_rejected_before_acquisition(path):
	store = Store()
	with TestClient(create_app(store)) as client:
		response = client.post(path)
		assert response.status_code == 405
		assert response.headers["allow"] == "GET"
		assert store.calls == 0


def test_data_failure_never_returns_demo_or_cacheable_success():
	store = Store(DataError("source_unavailable", "Dataset unavailable."))
	with TestClient(create_app(store)) as client:
		response = client.get("/api/market")
		assert response.status_code == 503
		assert response.json()["ok"] is False
		assert response.headers["cache-control"] == "no-store"
		assert response.json()["request_id"] == response.headers["x-request-id"]
		assert "DEMO" not in response.text


def test_stale_market_is_503_and_not_cached(monkeypatch):
	monkeypatch.setattr(
		"radar.app.market_snapshot",
		lambda data: {
			"ok": False,
			"status": "stale",
			"assets": [{"symbol": "SPY", "status": "stale"}],
		},
	)
	with TestClient(create_app(Store())) as client:
		response = client.get("/api/market")
		assert response.status_code == 503
		assert response.json()["status"] == "stale"
		assert response.headers["cache-control"] == "no-store"


def test_nonfinite_result_cannot_be_published(monkeypatch):
	monkeypatch.setattr(
		"radar.app.run_backtest", lambda data, params: {"ok": True, "nav": float("nan")}
	)
	with TestClient(create_app(Store())) as client:
		response = client.get("/api/backtest?start=2020-01-01")
		assert response.status_code == 500
		assert response.json()["error"]["code"] == "internal_error"


def test_static_routes_do_not_expose_repository_or_inputs():
	with TestClient(create_app(Store())) as client:
		assert client.get("/").status_code == 200
		for path in ("/.env", "/data/cracken.zip", "/pyproject.toml", "/radar/engine.py"):
			assert client.get(path).status_code == 404


async def test_results_coalesce_and_return_immutable_copies():
	cache, calls = ResultCache(), 0

	async def calculate():
		nonlocal calls
		calls += 1
		await asyncio.sleep(0.01)
		return {"results": [1]}

	first, second = await asyncio.gather(cache.get("same", calculate), cache.get("same", calculate))
	assert calls == 1
	first["results"].append(2)
	assert second == {"results": [1]}
	assert await cache.get("same", calculate) == second


async def test_failed_result_is_not_cached():
	cache = ResultCache()

	async def calculate():
		raise DataError("missing_history", "Missing observations")

	with pytest.raises(DataError):
		await cache.get("same", calculate)
	assert not cache.values and not cache.pending


async def test_slow_worker_keeps_capacity_until_it_finishes():
	import threading

	gate = threading.Event()
	budget = WorkBudget(concurrency=1, timeout=0.01)
	try:
		with pytest.raises(DataError, match="time budget"):
			await budget.run(gate.wait, 2)
		with pytest.raises(DataError, match="capacity"):
			await budget.run(lambda: 1)
	finally:
		gate.set()
	await asyncio.sleep(0.02)
	assert await budget.run(lambda: 1) == 1
	await budget.aclose()


async def test_cancelled_consumer_and_shutdown_drain_owned_workers():
	import threading

	gate = threading.Event()
	cache, work = ResultCache(), WorkBudget(concurrency=1)
	request = asyncio.create_task(cache.get("shared", lambda: work.run(gate.wait, 2)))
	await asyncio.sleep(0.02)
	request.cancel()
	with pytest.raises(asyncio.CancelledError):
		await request
	assert work.workers
	await cache.aclose()
	draining = asyncio.create_task(work.aclose())
	await asyncio.sleep(0.01)
	assert not draining.done()
	gate.set()
	await draining
	assert not work.workers and not cache.pending
	with pytest.raises(DataError, match="shutting down"):
		await cache.get("again", lambda: None)


async def test_shutdown_cannot_admit_a_worker_that_was_waiting_for_capacity():
	import threading

	gate, called = threading.Event(), []
	work = WorkBudget(concurrency=1)
	first = asyncio.create_task(work.run(gate.wait, 2))
	await asyncio.sleep(0.01)
	waiting = asyncio.create_task(work.run(lambda: called.append("escaped")))
	await asyncio.sleep(0.01)
	draining = asyncio.create_task(work.aclose())
	await asyncio.sleep(0.01)
	gate.set()
	await first
	await draining
	with pytest.raises(DataError, match="shutting down"):
		await waiting
	assert not called and not work.workers


def test_routed_compare_runs_actual_engine_on_one_snapshot():
	from engine_fixtures import flat_dataset

	store = Store()
	store.dataset = flat_dataset()
	with TestClient(create_app(store)) as client:
		response = client.get(
			"/api/backtest?start=2020-01-01&end=2021-04-01&mode=compare&cost_bps=0&short_borrow_bps=0"
		)
		assert response.status_code == 200, response.text
		body = response.json()
		assert set(body["results"]) == {"extreme1", "ranked3", "longonly3"}
		assert body["dataset_id"] == store.dataset.dataset_id
		assert body["period"]["first_execution"] == "2020-01-02"
		for key, result in body["results"].items():
			assert result["strategy"]["id"] == key
			assert result["stats"]["total_return"] == 0
			assert result["equity_curve"][-1]["strategy"] == 100
			assert result["stats"]["sharpe"] is None


def test_actual_missing_history_is_named_http_failure():
	from engine_fixtures import dataset_from_payload, fixture_payload

	payload = fixture_payload()
	del payload["series"]["XLC_TR"]
	store = Store()
	store.dataset = dataset_from_payload(payload)
	with TestClient(create_app(store)) as client:
		response = client.get("/api/backtest?start=2020-01-01")
		assert response.status_code == 503
		assert response.json()["error"]["code"] == "missing_series"
		assert "XLC_TR" in response.json()["error"]["details"]["series"]


def test_mock_mode_is_explicit_and_does_not_replace_a_real_source(monkeypatch):
	from radar.app import configured_store
	from radar.data import DatasetStore
	from radar.mock import MockDatasetStore

	for name in (
		"RADAR_DATA_MODE",
		"RADAR_DATASET_PATH",
		"RADAR_DATASET_URL",
		"RADAR_DATASET_TOKEN",
		"RADAR_MOCK_SEED",
	):
		monkeypatch.delenv(name, raising=False)
	assert isinstance(configured_store(), DatasetStore)
	monkeypatch.setenv("RADAR_DATA_MODE", "mock")
	monkeypatch.setenv("RADAR_MOCK_SEED", "12")
	store = configured_store()
	assert isinstance(store, MockDatasetStore) and store.seed == 12
	monkeypatch.setenv("RADAR_DATASET_PATH", "/private/real-snapshot.json")
	with pytest.raises(ValueError, match="Unset real"):
		configured_store()
	monkeypatch.delenv("RADAR_DATASET_PATH")
	monkeypatch.setenv("RADAR_MOCK_SEED", "NaN")
	with pytest.raises(ValueError, match="RADAR_MOCK_SEED"):
		configured_store()
	monkeypatch.setenv("RADAR_DATA_MODE", "demo")
	with pytest.raises(ValueError, match="RADAR_DATA_MODE"):
		configured_store()


@pytest.mark.parametrize(
	"path",
	["/api/analytics?source=http://example.invalid", "/api/studies?start=2020-01-01&top_n=8"],
)
def test_invalid_research_queries_never_acquire_data(path):
	store = Store()
	with TestClient(create_app(store)) as client:
		assert client.get(path).status_code == 400
		assert store.calls == 0


def test_actual_mock_feed_runs_all_feature_families_through_http():
	from radar.mock import MockDatasetStore

	with TestClient(create_app(MockDatasetStore(seed=8042))) as client:
		market = client.get("/api/market")
		assert market.status_code == 200, market.text
		identity = market.json()["dataset_id"]
		analytics = client.get("/api/analytics")
		assert analytics.status_code == 200, analytics.text
		assert set(analytics.json()["sections"]) == {
			"risk",
			"changes",
			"anomalies",
			"correlations",
			"rates",
			"volatility",
			"fx",
			"sectors",
			"playbook",
			"analogues",
		}
		assert all(
			section["status"] == "ready" for section in analytics.json()["sections"].values()
		)
		params = "start=2020-01-01&mode=compare&rebalance=weekly&top_n=5"
		backtest = client.get("/api/backtest?" + params)
		assert backtest.status_code == 200, backtest.text
		assert backtest.json()["params"]["rebalance"] == "weekly"
		assert backtest.json()["params"]["top_n"] == 5
		basket = backtest.json()["results"]["ranked3"]
		assert len(basket["holdings"][0]["weights"]) == 10
		assert basket["annual_returns"] and basket["benchmark_stats"] and basket["drawdown_curve"]
		studies = client.get("/api/studies?" + params)
		assert studies.status_code == 200, studies.text
		assert len(studies.json()["robustness"]) == 9
		assert len(studies.json()["cost_sensitivity"]) == 4
		health = client.get("/api/health")
		for response in (market, analytics, backtest, studies, health):
			assert response.json()["dataset_id"] == identity
			assert response.json()["source"]["kind"] == "mock"
			assert response.json()["source"]["seed"] == 8042
