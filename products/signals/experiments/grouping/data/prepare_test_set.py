"""
Extract a curated test dataset from the full signals export.

Reads a signals JSON export (one JSON array per line, as produced by posthog-cli)
and picks signals from specific reports to create a focused test set.

Usage:
    python products/signals/grouping-iterations/data/prepare_test_set.py --input /path/to/signals.json
"""

import os
import json
import logging
import argparse
from pathlib import Path

logger = logging.getLogger(__name__)

OUTPUT_PATH = Path(__file__).resolve().parent / "test_signals.json"

# Reports to include (all signals from each)
TARGET_REPORTS = {
    # Coherent group: date filtering / insights feature requests (9 signals)
    "019c91b8-3461-7070-848d-3bdae529f82c": "date-filtering",
    # Weak-chained group: mixed bag of unrelated signals (18 signals)
    # This is the key test case — a good strategy should split this into sub-groups
    "019c9198-9d78-7f02-a212-5a47954b8969": "mixed-bag",
    # Coherent group: k8s probes / feature flags infrastructure (8 signals)
    "019c91a6-b852-7db2-a655-049de3e58030": "k8s-flags",
    # Small coherent group: LLM analytics trace issues (2 signals)
    "019c921a-bffb-74cf-9993-5c4113d6ec89": "llm-traces",
}

# Number of singleton signals to include (from reports with only 1 signal in the export)
SINGLETON_COUNT = 5


def parse_signal_row(row: list) -> dict:
    """Parse a raw JSON array row from the signals export into a signal dict."""
    product, doc_type, document_id, timestamp, inserted_at, content, metadata_str = row
    metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
    return {
        "signal_id": document_id,
        "content": content,
        "source_product": metadata.get("source_product", ""),
        "source_type": metadata.get("source_type", ""),
        "source_id": metadata.get("source_id", ""),
        "weight": metadata.get("weight", 1.0),
        "timestamp": timestamp,
        "extra": metadata.get("extra", {}),
        "original_report_id": metadata.get("report_id", ""),
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare test signal set from ClickHouse export")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the signals JSON export (one JSON array per line, from posthog-cli)",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_PATH),
        help=f"Output path for the test set (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not input_path.exists():
        logger.error("Signals export not found at %s", input_path)
        logger.error(
            "Export with: posthog-cli exp query run \"select product, document_type, document_id, timestamp, inserted_at, content, metadata from document_embeddings where model_name = 'text-embedding-3-small-1536' and product = 'signals' limit 1000\" > signals.json"
        )
        return

    # Parse all signals and group by report_id
    signals_by_report: dict[str, list[dict]] = {}

    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            signal = parse_signal_row(row)
            rid = signal["original_report_id"]
            if rid:
                signals_by_report.setdefault(rid, []).append(signal)

    test_signals: list[dict] = []

    # Add all signals from target reports
    for report_id, label in TARGET_REPORTS.items():
        report_signals = signals_by_report.get(report_id, [])
        count = len(report_signals)
        test_signals.extend(report_signals)
        logger.info("  [%s] %s: %d signals", label, report_id, count)

    # Add singleton signals (from reports that have exactly 1 signal in our export)
    singleton_reports = [rid for rid, sigs in signals_by_report.items() if len(sigs) == 1 and rid not in TARGET_REPORTS]
    added_singletons = 0
    for rid in singleton_reports:
        if added_singletons >= SINGLETON_COUNT:
            break
        test_signals.extend(signals_by_report[rid])
        content_preview = signals_by_report[rid][0]["content"][:80]
        logger.info("  [singleton] %s: %s", rid, content_preview)
        added_singletons += 1

    # Sort by timestamp to simulate arrival order
    test_signals.sort(key=lambda s: s["timestamp"])

    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(test_signals, f, indent=2)

    logger.info("Wrote %d signals to %s", len(test_signals), output_path)


if __name__ == "__main__":
    main()
