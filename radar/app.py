"""HTTP boundary for the canonical radar engine and validated snapshot distribution."""

from __future__ import annotations

import asyncio
import json
import math
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from radar import __version__
from radar.data import DataError, DatasetStore
from radar.engine import BacktestParams, run_backtest
from radar.market import market_snapshot

ROOT = Path(__file__).resolve().parent.parent
LOGGER = structlog.get_logger("radar.http")
ALIASES = {"costBps": "cost_bps", "shortBorrowBps": "short_borrow_bps"}
PARAMETERS = {"start", "end", "mode", "cost_bps", "short_borrow_bps", "rebalance"}


class WorkBudget:
	"""Bound CPU work; timed-out readers cannot release still-running worker slots."""

	def __init__(self, concurrency: int = 2, timeout: float = 15) -> None:
		self.slots = asyncio.BoundedSemaphore(concurrency)
		self.timeout = timeout
		self.workers: set[asyncio.Task] = set()
		self.closed = False

	async def run(self, function: Callable, *args: Any) -> Any:
		if self.closed:
			raise DataError("service_shutting_down", "Research service is shutting down.")
		try:
			await asyncio.wait_for(self.slots.acquire(), timeout=0.1)
		except TimeoutError as exc:
			raise DataError("busy", "Research capacity is busy; retry shortly.") from exc
		task = asyncio.create_task(asyncio.to_thread(function, *args))
		self.workers.add(task)

		def finished(completed: asyncio.Task) -> None:
			self.workers.discard(completed)
			self.slots.release()
			if not completed.cancelled():
				completed.exception()

		task.add_done_callback(finished)
		try:
			return await asyncio.wait_for(asyncio.shield(task), self.timeout)
		except TimeoutError as exc:
			# The bounded, read-only worker retains its slot until it actually exits.
			raise DataError("calculation_timeout", "Calculation exceeded its time budget.") from exc

	async def aclose(self) -> None:
		"""Drain owned bounded CPU jobs; cancellation cannot safely kill a thread."""
		self.closed = True
		if self.workers:
			await asyncio.gather(*tuple(self.workers), return_exceptions=True)


class ResultCache:
	"""Small immutable-result cache and in-flight coalescer, keyed by dataset and parameters."""

	def __init__(self, capacity: int = 16) -> None:
		self.capacity = capacity
		self.values: OrderedDict[str, bytes] = OrderedDict()
		self.pending: dict[str, asyncio.Task] = {}
		self.closed = False

	async def get(self, key: str, factory: Callable) -> dict:
		if self.closed:
			raise DataError("service_shutting_down", "Research service is shutting down.")
		if key in self.values:
			self.values.move_to_end(key)
			return json.loads(self.values[key])
		if key not in self.pending:

			async def populate() -> bytes:
				try:
					result = await factory()
					encoded = json.dumps(jsonable_encoder(result), allow_nan=False).encode()
					if len(encoded) > 2 * 1024 * 1024:
						raise DataError("result_too_large", "Result exceeds the publication limit.")
					self.values[key] = encoded
					while len(self.values) > self.capacity:
						self.values.popitem(last=False)
					return encoded
				finally:
					self.pending.pop(key, None)

			self.pending[key] = asyncio.create_task(populate())
			self.pending[key].add_done_callback(
				lambda completed: None if completed.cancelled() else completed.exception()
			)
		return json.loads(await asyncio.shield(self.pending[key]))

	async def aclose(self) -> None:
		"""Cancel orchestration; WorkBudget owns draining its actual CPU workers."""
		self.closed = True
		tasks = tuple(self.pending.values())
		for task in tasks:
			task.cancel()
		if tasks:
			await asyncio.gather(*tasks, return_exceptions=True)
		self.values.clear()


def parse_backtest_params(request: Request) -> BacktestParams:
	"""Reject ambiguous query values before touching the data store."""
	if len(request.url.query) > 2048:
		raise DataError("invalid_parameters", "Query exceeds the supported size.")
	values = {}
	for key, value in request.query_params.multi_items():
		name = ALIASES.get(key, key)
		if name not in PARAMETERS:
			raise DataError("invalid_parameters", f"Unsupported parameter: {name[:64]}")
		if name in values:
			raise DataError("invalid_parameters", f"Parameter must occur once: {name}")
		if name in {"cost_bps", "short_borrow_bps"}:
			try:
				number = float(value)
			except ValueError as exc:
				raise DataError("invalid_parameters", f"{name} must be a finite number.") from exc
			if not value.strip() or not math.isfinite(number):
				raise DataError("invalid_parameters", f"{name} must be a finite number.")
			values[name] = number
		else:
			values[name] = value
	return BacktestParams.model_validate(values)


def _error(request: Request, code: str, message: str, status: int, details=None) -> JSONResponse:
	return JSONResponse(
		{
			"ok": False,
			"error": {"code": code, "message": message, "details": details},
			"request_id": request.state.request_id,
		},
		status_code=status,
		headers={"Cache-Control": "no-store", **({"Retry-After": "5"} if code == "busy" else {})},
	)


def create_app(store=None) -> FastAPI:
	"""Create an app without opening a provider/database connection during import."""

	@asynccontextmanager
	async def lifespan(application: FastAPI):
		application.state.store = store if store is not None else DatasetStore()
		application.state.work = WorkBudget()
		application.state.results = ResultCache()
		try:
			yield
		finally:
			await application.state.results.aclose()
			await application.state.work.aclose()
			await application.state.store.aclose()

	application = FastAPI(
		title="Market Regime Radar",
		version=__version__,
		lifespan=lifespan,
		docs_url=None,
		redoc_url=None,
		openapi_url="/api/openapi.json",
	)

	@application.middleware("http")
	async def request_boundary(request: Request, call_next):
		request.state.request_id = uuid.uuid4().hex
		started = time.monotonic()
		try:
			response = await call_next(request)
		except Exception as exc:
			LOGGER.error(
				"request_exception",
				request_id=request.state.request_id,
				failure_type=type(exc).__name__,
				stack_frames=[
					{
						"file": Path(frame.filename).name,
						"line": frame.lineno,
						"function": frame.name,
					}
					for frame in traceback.extract_tb(exc.__traceback__)
				],
			)
			response = _error(
				request, "internal_error", "Request failed. Use the request ID for support.", 500
			)
		response.headers["X-Request-ID"] = request.state.request_id
		response.headers["X-Content-Type-Options"] = "nosniff"
		response.headers["Referrer-Policy"] = "same-origin"
		response.headers["Content-Security-Policy"] = (
			"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
			"connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
		)
		if request.url.path.startswith("/api/"):
			LOGGER.info(
				"request_complete",
				request_id=request.state.request_id,
				path=request.url.path,
				method=request.method,
				status=response.status_code,
				duration_ms=round((time.monotonic() - started) * 1000, 1),
			)
		return response

	@application.exception_handler(DataError)
	async def data_error(request: Request, exc: DataError):
		LOGGER.warning("data_failure", request_id=request.state.request_id, code=exc.code)
		status = 400 if exc.code == "invalid_parameters" else 503
		if exc.code == "busy":
			status = 429
		return _error(request, exc.code, str(exc), status, getattr(exc, "details", None))

	@application.exception_handler(ValidationError)
	async def validation_error(request: Request, exc: ValidationError):
		details = [
			{"field": ".".join(map(str, e["loc"])), "reason": e["msg"]} for e in exc.errors()
		]
		return _error(request, "invalid_parameters", "Invalid request parameters.", 400, details)

	@application.exception_handler(HTTPException)
	async def http_error(request: Request, exc: HTTPException):
		response = _error(
			request,
			"method_not_allowed" if exc.status_code == 405 else "not_found",
			"Method not allowed." if exc.status_code == 405 else "Resource not found.",
			exc.status_code,
		)
		if exc.headers:
			response.headers.update(exc.headers)
		return response

	@application.get("/api/market")
	async def market(request: Request):
		if request.query_params:
			raise DataError("invalid_parameters", "Market endpoint accepts no query parameters.")
		dataset = await request.app.state.store.get()
		result = await request.app.state.work.run(market_snapshot, dataset)
		ready = result.get("status") == "ready"
		return JSONResponse(
			jsonable_encoder(result),
			status_code=200 if ready else 503,
			headers={"Cache-Control": "private, max-age=30" if ready else "no-store"},
		)

	params_schema = BacktestParams.model_json_schema()

	@application.get(
		"/api/backtest",
		openapi_extra={
			"parameters": [
				{
					"name": name,
					"in": "query",
					"required": name in params_schema.get("required", []),
					"schema": schema,
				}
				for name, schema in params_schema["properties"].items()
			]
		},
	)
	async def backtest(request: Request):
		params = parse_backtest_params(request)
		dataset = await request.app.state.store.get()
		key = f"{dataset.dataset_id}:{params.model_dump_json()}"
		result = await request.app.state.results.get(
			key, lambda: request.app.state.work.run(run_backtest, dataset, params)
		)
		return JSONResponse(result, headers={"Cache-Control": "private, no-cache"})

	@application.get("/api/health")
	async def health(request: Request):
		dataset = await request.app.state.store.get()
		readiness = await request.app.state.work.run(market_snapshot, dataset)
		ready = readiness.get("status") == "ready"
		return JSONResponse(
			{
				"ok": ready,
				"status": readiness.get("status"),
				"version": __version__,
				"dataset_id": dataset.dataset_id,
				"as_of": dataset.as_of.isoformat(),
			},
			status_code=200 if ready else 503,
			headers={"Cache-Control": "no-store"},
		)

	@application.get("/", include_in_schema=False)
	async def index():
		return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})

	@application.get("/api/model")
	async def model():
		return FileResponse(ROOT / "engine-spec.json", headers={"Cache-Control": "no-cache"})

	application.mount(
		"/static", StaticFiles(directory=ROOT / "static", check_dir=False), name="static"
	)
	return application


__all__ = ["create_app", "parse_backtest_params"]
