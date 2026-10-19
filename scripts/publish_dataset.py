"""Validate and atomically publish a data_mesh export; never query upstream providers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.data import MAX_BYTES, DataError, Dataset, dataset_content_id, parse_dataset

SECTORS = {"XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY"}
REQUIRED_SERIES = (
	SECTORS
	| {"SPY", "QQQ", "GLD", "USO", "UUP"}
	| {f"{symbol}_TR" for symbol in SECTORS | {"SPY", "QQQ", "GLD", "USO", "UUP"}}
	| {"DGS2", "DGS5", "DGS10", "DGS30", "DFII10", "T10YIE", "VIXCLS", "BAMLH0A0HYM2", "DFF"}
)


def publish_dataset(source: Path, destination: Path, *, allow_partial: bool = False) -> Dataset:
	"""Validate before writing, preserve immutable versions and replace the pointer.

	The producer must supply genuine availability timestamps, the complete NYSE
	calendar and historical vintages. This utility never infers or fabricates them.
	"""
	with source.open("rb") as stream:
		payload = stream.read(MAX_BYTES + 1)
	if len(payload) > MAX_BYTES:
		raise DataError("dataset_too_large", "Input exceeds the 32 MiB publication limit")
	try:

		def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
			result = {}
			for key, value in pairs:
				if key in result:
					raise ValueError("Duplicate JSON key")
				result[key] = value
			return result

		raw = json.loads(payload, object_pairs_hook=unique_pairs)
		if "dataset_id" not in raw:
			raw["dataset_id"] = dataset_content_id(raw)
		dataset = parse_dataset(json.dumps(raw, allow_nan=False).encode())
	except (ValueError, TypeError, KeyError) as exc:
		raise DataError("invalid_dataset", "Input failed the publication contract") from exc
	missing = sorted(REQUIRED_SERIES - dataset.series.keys())
	if missing and not allow_partial:
		raise DataError(
			"incomplete_dataset", "Required radar series are absent", {"missing_series": missing}
		)
	encoded = dataset.model_dump_json().encode()
	destination.parent.mkdir(parents=True, exist_ok=True)
	versions = destination.parent / "versions"
	versions.mkdir(exist_ok=True)
	archive = versions / f"{dataset.dataset_id.removeprefix('sha256:')}.json"
	temporary: str | None = None
	try:
		with tempfile.NamedTemporaryFile(
			dir=destination.parent, prefix=".radar-", delete=False
		) as stream:
			temporary = stream.name
			stream.write(encoded)
			stream.flush()
			os.fsync(stream.fileno())
		try:
			# Link only the completely written file. Existing immutable versions
			# are verified rather than overwritten, including concurrent publishers.
			os.link(temporary, archive)
		except FileExistsError:
			with archive.open("rb") as stream:
				stored = parse_dataset(stream.read(MAX_BYTES + 1))
			if stored.dataset_id != dataset.dataset_id:
				raise DataError("dataset_identity_conflict", "The archived content is inconsistent")
		archive_directory = os.open(versions, os.O_RDONLY)
		try:
			os.fsync(archive_directory)
		finally:
			os.close(archive_directory)
		os.replace(temporary, destination)
		temporary = None
		directory = os.open(destination.parent, os.O_RDONLY)
		try:
			os.fsync(directory)
		finally:
			os.close(directory)
	finally:
		if temporary is not None:
			Path(temporary).unlink(missing_ok=True)
	return dataset


def main() -> int:
	"""Run the offline publication command and print only safe output metadata."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"source", type=Path, help="Validated exporter JSON, with optional dataset_id"
	)
	parser.add_argument(
		"destination", type=Path, help="Local current snapshot path used by RADAR_DATASET_PATH"
	)
	parser.add_argument(
		"--allow-partial",
		action="store_true",
		help="Publish a partial onboarding snapshot; missing panels remain unavailable",
	)
	args = parser.parse_args()
	try:
		dataset = publish_dataset(args.source, args.destination, allow_partial=args.allow_partial)
	except (DataError, OSError) as exc:
		print(
			json.dumps(
				{
					"ok": False,
					"error": {
						"code": getattr(exc, "code", "publication_failed"),
						"message": getattr(
							exc, "message", "Cannot read or write the publication paths"
						),
						"details": getattr(exc, "details", None),
					},
				}
			),
			file=sys.stderr,
		)
		return 1
	print(
		json.dumps(
			{
				"ok": True,
				"dataset_id": dataset.dataset_id,
				"as_of": dataset.as_of.isoformat(),
				"series_count": len(dataset.series),
			}
		)
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
