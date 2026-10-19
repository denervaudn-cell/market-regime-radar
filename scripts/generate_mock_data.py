"""Write an explicit synthetic snapshot for offline preview; never call providers."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radar.mock import DEFAULT_SEED, generate_mock_dataset


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("output", type=Path)
	parser.add_argument("--as-of", type=date.fromisoformat)
	parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
	args = parser.parse_args()
	if args.output.exists():
		parser.error("Output already exists; choose a new path to preserve existing snapshots")
	dataset = generate_mock_dataset(args.as_of, seed=args.seed)
	args.output.parent.mkdir(parents=True, exist_ok=True)
	with args.output.open("x") as stream:
		stream.write(dataset.model_dump_json())
	print(f"MOCK inputs: {len(dataset.series)} series, as of {dataset.as_of}, {dataset.dataset_id}")


if __name__ == "__main__":
	main()
