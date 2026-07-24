"""Convert Rust pair-feature JSONL to a compact Parquet feature table."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
from pathlib import Path

import pyarrow.json as arrow_json
import pyarrow.parquet as parquet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output)
    table = arrow_json.read_json(args.input, read_options=arrow_json.ReadOptions(block_size=64 * 1024 * 1024))
    if not table.num_rows:
        raise ValueError("empty pair-feature input")
    parquet.write_table(table, output, compression="zstd")
    print(f"wrote {table.num_rows} rows to {output}")


if __name__ == "__main__":
    main()
