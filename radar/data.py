"""Validated, immutable market datasets and bounded snapshot acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import random
import re
import stat
import time
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from urllib.parse import urlparse

import exchange_calendars
import httpx
from pydantic import (
	BaseModel,
	ConfigDict,
	Field,
	ValidationError,
	field_serializer,
	field_validator,
	model_validator,
)

MAX_OBSERVATIONS = 250_000
MAX_BYTES = 32 * 1024 * 1024
_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
_MISSING = {"", ".", "na", "n/a", "null", "none", "nan", "-", "--"}


@lru_cache(maxsize=8)
def exchange_sessions(start: date, end: date) -> tuple[date, ...]:
	"""Return independently verified NYSE sessions in a bounded date interval."""
	if start < date(1990, 1, 1) or end > date.today() + timedelta(days=740) or end < start:
		raise ValueError("Calendar is outside the supported 1990 through today+2 years range")
	calendar = exchange_calendars.get_calendar(
		"XNYS",
		start=start.isoformat(),
		end=(end + timedelta(days=1) if end == start else end).isoformat(),
	)
	return tuple(day for day in calendar.sessions.date if start <= day <= end)


class DataError(Exception):
	"""A safe data-boundary error suitable for an API response."""

	def __init__(self, code: str, message: str, details: Any = None) -> None:
		super().__init__(message)
		self.code = code
		self.message = message
		self.details = details


def _strict_date(value: Any) -> date:
	if isinstance(value, datetime):
		raise ValueError("A date must not include a time")
	if isinstance(value, date):
		return value
	if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
		raise ValueError("Expected an ISO calendar date")
	return date.fromisoformat(value)


def _aware_datetime(value: Any) -> datetime:
	if isinstance(value, str):
		value = datetime.fromisoformat(value.replace("Z", "+00:00"))
	if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
		raise ValueError("Expected an ISO timestamp with a timezone")
	return value.astimezone(UTC)


class Observation(BaseModel):
	"""An observation and the instant this particular version became available."""

	model_config = ConfigDict(extra="forbid", frozen=True)
	date: date
	value: float
	available_at: datetime

	_date = field_validator("date", mode="before")(_strict_date)
	_timestamp = field_validator("available_at", mode="before")(_aware_datetime)

	@field_validator("value", mode="before")
	@classmethod
	def finite_value(cls, value: Any) -> float:
		"""Reject raw missing tokens and coercions before doing any arithmetic."""
		if isinstance(value, str) and value.strip().lower() in _MISSING:
			raise ValueError("Missing observation values must be omitted, not replaced by zero")
		if isinstance(value, bool) or not isinstance(value, (int, float)):
			raise ValueError("Observation values must be JSON numbers")
		if not math.isfinite(value):
			raise ValueError("Observation values must be finite")
		return float(value)

	@model_validator(mode="after")
	def availability_order(self) -> Observation:
		if self.available_at.date() < self.date:
			raise ValueError("Availability cannot precede the observation date")
		return self


class Series(BaseModel):
	"""A versioned series with explicit provider, units and return convention."""

	model_config = ConfigDict(extra="forbid", frozen=True)
	id: str = Field(min_length=1, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
	source: str = Field(min_length=1, max_length=120)
	unit: str = Field(min_length=1, max_length=30)
	price_basis: str
	observations: tuple[Observation, ...] = Field(min_length=1, max_length=30_000)
	currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

	@field_validator("source", "unit", "price_basis")
	@classmethod
	def clean_metadata(cls, value: str) -> str:
		"""Keep metadata printable and reject ambiguous empty or padded labels."""
		if value != value.strip() or not value or any(ord(char) < 32 for char in value):
			raise ValueError("Metadata must be nonempty printable text without outer whitespace")
		return value

	@model_validator(mode="after")
	def conventions(self) -> Series:
		allowed = {"close", "total_return_net", "total_return_gross", "rate", "index", "fx"}
		if self.price_basis not in allowed:
			raise ValueError("Unsupported price basis")
		if (
			self.price_basis in {"total_return_net", "total_return_gross", "index"}
			and self.unit != "index"
		):
			raise ValueError("Return and other indices require unit=index")
		if self.price_basis == "rate" and self.unit != "percent":
			raise ValueError("Rates require native percent units, never basis points or fractions")
		if self.price_basis == "close" and (self.currency is None or self.unit != self.currency):
			raise ValueError("Quoted closes require matching currency and unit")
		keys = [(row.date, row.available_at) for row in self.observations]
		if keys != sorted(keys) or len(keys) != len(set(keys)):
			raise ValueError("Observations must be ordered and unique by date/availability")
		for row in self.observations:
			if self.price_basis != "rate" and row.value <= 0:
				raise ValueError("Prices, FX and indices must be strictly positive")
			if (self.price_basis == "rate" and not -100 <= row.value <= 1000) or abs(
				row.value
			) > 1e15:
				raise ValueError("Value exceeds the declared data contract bounds")
		return self


class DatasetSource(BaseModel):
	"""Explicit origin of values; mock status is part of immutable content identity."""

	model_config = ConfigDict(extra="forbid", frozen=True)
	kind: Literal["real", "mock"]
	label: str = Field(min_length=1, max_length=160)
	seed: int | None = Field(default=None, strict=True, ge=0, le=2**32 - 1)

	@field_validator("label")
	@classmethod
	def printable_label(cls, value: str) -> str:
		if value != value.strip() or any(ord(char) < 32 for char in value):
			raise ValueError("Source label must be printable without outer whitespace")
		return value

	@model_validator(mode="after")
	def mock_seed_only(self) -> DatasetSource:
		if self.kind == "real" and self.seed is not None:
			raise ValueError("A generator seed applies only to mock inputs")
		return self


def dataset_content_id(payload: Mapping[str, Any] | Dataset) -> str:
	"""Hash normalized financial content, excluding the producer-supplied identity.

	All timestamps normalize to UTC and numeric observations to floats. This makes
	identical validated content stable across harmless JSON formatting differences.
	"""
	if isinstance(payload, Dataset):
		content = payload.model_dump(mode="json", exclude={"dataset_id", "source"})
		if payload.source is not None:
			content["source"] = payload.source.model_dump(mode="json")
	else:
		content = {
			"schema_version": payload.get("schema_version", 1),
			"generated_at": _aware_datetime(payload["generated_at"])
			.isoformat()
			.replace("+00:00", "Z"),
			"as_of": _strict_date(payload["as_of"]).isoformat(),
			"calendar": [_strict_date(day).isoformat() for day in payload["calendar"]],
			"series": {
				key: (
					value if isinstance(value, Series) else Series.model_validate(value)
				).model_dump(mode="json")
				for key, value in payload["series"].items()
			},
		}
		if payload.get("source") is not None:
			content["source"] = DatasetSource.model_validate(payload["source"]).model_dump(
				mode="json"
			)
	encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
	return "sha256:" + hashlib.sha256(encoded).hexdigest()


class Dataset(BaseModel):
	"""An immutable snapshot whose identifier identifies its complete content."""

	model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)
	schema_version: int = Field(default=1, strict=True)
	dataset_id: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
	generated_at: datetime
	as_of: date
	calendar: tuple[date, ...] = Field(min_length=1, max_length=20_000)
	series: Mapping[str, Series]
	source: DatasetSource | None = None

	_generated = field_validator("generated_at", mode="before")(_aware_datetime)
	_as_of = field_validator("as_of", mode="before")(_strict_date)

	@field_validator("calendar", mode="before")
	@classmethod
	def calendar_dates(cls, values: Any) -> tuple[date, ...]:
		"""Reject timestamps or coercible numbers in the exchange calendar."""
		if not isinstance(values, (tuple, list)):
			raise ValueError("Calendar must be an ordered array")
		return tuple(_strict_date(value) for value in values)

	@field_validator("series", mode="before")
	@classmethod
	def bounded_series(cls, values: Any) -> Any:
		"""Apply allocation limits before Pydantic expands observations."""
		if not isinstance(values, Mapping) or not 1 <= len(values) <= 80:
			raise ValueError("A dataset must contain between 1 and 80 series")
		total = 0
		for key, value in values.items():
			if not isinstance(key, str) or not _IDENTIFIER.fullmatch(key):
				raise ValueError("Invalid series key")
			rows = (
				value.observations
				if isinstance(value, Series)
				else value.get("observations", [])
				if isinstance(value, Mapping)
				else []
			)
			total += len(rows)
		if total > MAX_OBSERVATIONS:
			raise ValueError("Dataset observation budget exceeded")
		return values

	@field_serializer("series")
	def serialize_series(self, value: Mapping[str, Series]) -> dict[str, Any]:
		"""Serialize immutable mappings as ordinary JSON objects."""
		return {key: series.model_dump(mode="json") for key, series in value.items()}

	@model_validator(mode="after")
	def coherent_snapshot(self) -> Dataset:
		if self.schema_version != 1:
			raise ValueError("Unsupported dataset schema version")
		if tuple(sorted(set(self.calendar))) != self.calendar:
			raise ValueError("Calendar sessions must be unique and ascending")
		if self.calendar[0] > self.as_of or self.as_of > self.generated_at.date():
			raise ValueError("Snapshot dates are inconsistent")
		if any(day.weekday() > 4 for day in self.calendar):
			raise ValueError("NYSE calendar cannot contain weekend sessions")
		if self.calendar != exchange_sessions(self.calendar[0], self.calendar[-1]):
			raise ValueError("Calendar omits or invents an NYSE trading session")
		if self.calendar[-1] > self.as_of + timedelta(days=740):
			raise ValueError("Calendar forecast exceeds two years")
		session_set = set(self.calendar)
		for key, series in self.series.items():
			if series.id != key:
				raise ValueError("Series key must match its id")
			if any(
				row.date > self.as_of or row.available_at > self.generated_at
				for row in series.observations
			):
				raise ValueError("Snapshot contains future observations or unavailable versions")
			if series.price_basis in {"close", "total_return_net", "total_return_gross"} and any(
				row.date not in session_set for row in series.observations
			):
				raise ValueError("ETF observations must fall on supplied NYSE calendar sessions")
		if dataset_content_id(self) != self.dataset_id:
			raise ValueError("Dataset content does not match its immutable identifier")
		object.__setattr__(self, "series", MappingProxyType(dict(self.series)))
		return self


def parse_dataset(payload: bytes, *, max_bytes: int = MAX_BYTES) -> Dataset:
	"""Validate an acquired snapshot without disclosing raw provider values."""
	if len(payload) > max_bytes:
		raise DataError("dataset_too_large", "The dataset exceeds the configured size limit")
	try:

		def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
			result: dict[str, Any] = {}
			for key, value in pairs:
				if key in result:
					raise ValueError("Duplicate JSON key")
				result[key] = value
			return result

		raw = json.loads(payload, object_pairs_hook=unique_object)
		return Dataset.model_validate(raw)
	except (ValueError, TypeError, KeyError, RecursionError) as exc:
		details = None
		if isinstance(exc, ValidationError):
			details = [
				{"field": ".".join(map(str, item["loc"])), "type": item["type"]}
				for item in exc.errors()[:12]
			]
		raise DataError(
			"invalid_dataset", "The supplied dataset failed contract validation", details
		) from exc


class DatasetStore:
	"""Load one configured snapshot with bounded I/O, retries and shared acquisition.

	There is no stale-on-error success path. Cancelling an individual consumer does
	not cancel a shared fetch; cancelling the last consumer cancels owned work.
	"""

	def __init__(
		self,
		*,
		path: str | Path | None = None,
		url: str | None = None,
		token: str | None = None,
		cache_ttl_seconds: float = 300,
		deadline_seconds: float = 10,
		max_bytes: int = MAX_BYTES,
		retries: int = 2,
		client: httpx.AsyncClient | None = None,
	) -> None:
		if path is None and url is None:
			path = os.environ.get("RADAR_DATASET_PATH")
			url = os.environ.get("RADAR_DATASET_URL")
		token = token if token is not None else os.environ.get("RADAR_DATASET_TOKEN")
		if token is not None and (
			not 1 <= len(token) <= 4096 or any(not 33 <= ord(char) <= 126 for char in token)
		):
			raise ValueError("Invalid dataset authentication token")
		if path and url:
			raise ValueError("Configure exactly one dataset source")
		if url:
			parsed = urlparse(url)
			if (
				parsed.scheme != "https"
				or not parsed.netloc
				or parsed.username
				or parsed.password
				or parsed.fragment
			):
				raise ValueError(
					"Dataset URL must be a fixed HTTPS URL without embedded credentials"
				)
		if (
			not 0 <= cache_ttl_seconds <= 3600
			or not 0 < deadline_seconds <= 25
			or not 0 <= retries <= 3
		):
			raise ValueError("Invalid dataset acquisition budget")
		if not 1 <= max_bytes <= MAX_BYTES:
			raise ValueError("Invalid dataset size limit")
		self.path = Path(path) if path else None
		self.url = url
		self._token = token
		self.cache_ttl_seconds = cache_ttl_seconds
		self.deadline_seconds = deadline_seconds
		self.max_bytes = max_bytes
		self.retries = retries
		self._client = client
		self._owns_client = client is None
		self._cache: Dataset | None = None
		self._expires_at = 0.0
		self._task: asyncio.Task[Dataset] | None = None
		self._validation_task: asyncio.Task[Dataset] | None = None
		self._file_task: asyncio.Task[bytes] | None = None
		self._waiters = 0
		self._closed = False

	async def get(self) -> Dataset:
		"""Return a validated snapshot, coalescing concurrent callers."""
		if self._closed:
			raise DataError("dataset_store_closed", "The dataset service is shutting down")
		if self._cache is not None and time.monotonic() < self._expires_at:
			return self._cache
		if self._task is None or self._task.done():
			if any(
				task is not None and not task.done()
				for task in (self._validation_task, self._file_task)
			):
				raise DataError(
					"dataset_busy", "Previous dataset acquisition is still releasing resources"
				)
			self._task = asyncio.create_task(self._load())
		task = self._task
		self._waiters += 1
		try:
			return await asyncio.shield(task)
		finally:
			self._waiters -= 1
			if self._waiters == 0 and not task.done():
				task.cancel()
				await asyncio.gather(task, return_exceptions=True)

	async def _load(self) -> Dataset:
		try:
			async with asyncio.timeout(self.deadline_seconds):
				if self.path:
					self._file_task = asyncio.create_task(asyncio.to_thread(self._read_file))
					self._file_task.add_done_callback(
						lambda task: task.exception() if not task.cancelled() else None
					)
					payload = await asyncio.shield(self._file_task)
				elif self.url:
					payload = await self._read_url()
				else:
					raise DataError(
						"dataset_not_configured",
						"Set RADAR_DATASET_PATH or RADAR_DATASET_URL to a validated data_mesh snapshot",
					)
				self._validation_task = asyncio.create_task(
					asyncio.to_thread(parse_dataset, payload, max_bytes=self.max_bytes)
				)
				# A timed-out worker cannot be forcibly stopped. Retain its ownership,
				# consume failures and admit no replacement until it actually exits.
				self._validation_task.add_done_callback(
					lambda task: task.exception() if not task.cancelled() else None
				)
				dataset = await asyncio.shield(self._validation_task)
				if dataset.generated_at > datetime.now(UTC) + timedelta(minutes=5):
					raise DataError("future_dataset", "Dataset generation time is in the future")
				self._cache = dataset
				self._expires_at = time.monotonic() + self.cache_ttl_seconds
				return dataset
		except TimeoutError as exc:
			raise DataError("dataset_timeout", "Dataset acquisition exceeded its deadline") from exc
		except OSError as exc:
			raise DataError(
				"dataset_unavailable", "The configured dataset could not be read"
			) from exc

	def _read_file(self) -> bytes:
		if self.path is None:
			raise DataError("dataset_not_configured", "No local dataset is configured")
		descriptor = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
		with os.fdopen(descriptor, "rb") as stream:
			if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
				raise DataError(
					"invalid_dataset_source", "The local dataset must be a regular file"
				)
			payload = stream.read(self.max_bytes + 1)
		if len(payload) > self.max_bytes:
			raise DataError("dataset_too_large", "The dataset exceeds the configured size limit")
		return payload

	async def _read_url(self) -> bytes:
		if self._client is None:
			self._client = httpx.AsyncClient(
				timeout=httpx.Timeout(5),
				limits=httpx.Limits(max_connections=1),
				follow_redirects=False,
				trust_env=False,
			)
		started = time.monotonic()
		headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
		if self._token:
			headers["Authorization"] = f"Bearer {self._token}"
		for attempt in range(self.retries + 1):
			retry_after = 0.1 * (2**attempt) + random.uniform(0, 0.05)
			try:
				async with self._client.stream(
					"GET", self.url, headers=headers, follow_redirects=False
				) as response:
					if (
						response.headers.get("Content-Encoding", "identity").strip().lower()
						!= "identity"
					):
						raise DataError(
							"dataset_encoding_unsupported",
							"Dataset distribution must serve uncompressed JSON",
						)
					if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
						value = response.headers.get("Retry-After", "")
						if value.isdigit():
							retry_after = float(value)
						elif value:
							try:
								retry_date = parsedate_to_datetime(value)
								if retry_date.tzinfo is not None:
									retry_after = max(
										0, (retry_date - datetime.now(UTC)).total_seconds()
									)
							except (ValueError, TypeError, OverflowError):
								pass  # A malformed server header does not alter bounded backoff.
						if attempt == self.retries:
							raise DataError(
								"dataset_upstream_unavailable",
								"Dataset distribution is temporarily unavailable",
							)
					elif response.status_code != 200:
						raise DataError(
							"dataset_upstream_rejected", "Dataset distribution rejected the request"
						)
					else:
						length = response.headers.get("Content-Length")
						if length and length.isdigit() and int(length) > self.max_bytes:
							raise DataError(
								"dataset_too_large", "The dataset exceeds the configured size limit"
							)
						payload = bytearray()
						async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
							payload.extend(chunk)
							if len(payload) > self.max_bytes:
								raise DataError(
									"dataset_too_large",
									"The dataset exceeds the configured size limit",
								)
						return bytes(payload)
			except httpx.RequestError as exc:
				if attempt == self.retries:
					raise DataError(
						"dataset_upstream_unavailable", "Dataset distribution could not be reached"
					) from exc
			if retry_after >= self.deadline_seconds - (time.monotonic() - started):
				raise DataError(
					"dataset_retry_later",
					"Dataset distribution requested a retry beyond the remaining deadline",
				)
			await asyncio.sleep(retry_after)
		raise DataError("dataset_upstream_unavailable", "Dataset distribution could not be reached")

	async def aclose(self) -> None:
		"""Cancel owned acquisition and release the owned HTTP client."""
		self._closed = True
		if self._task and not self._task.done():
			self._task.cancel()
			await asyncio.gather(self._task, return_exceptions=True)
		if self._validation_task:
			await asyncio.gather(self._validation_task, return_exceptions=True)
		if self._file_task:
			await asyncio.gather(self._file_task, return_exceptions=True)
		if self._owns_client and self._client:
			await self._client.aclose()
