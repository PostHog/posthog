from __future__ import annotations

import argparse
import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .config import load_config
from .io import JsonObject, canonical_json, read_jsonl, require_string


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Append one reviewed event to a pipeline-training label ledger")
    result.add_argument("config", type=Path)
    result.add_argument("ledger", choices=("llm", "human"))
    result.add_argument("event", type=Path, help="JSON object containing the candidate judgment")
    return result


def main() -> None:
    arguments = parser().parse_args()
    config = load_config(arguments.config)
    value = json.loads(arguments.event.read_text())
    if not isinstance(value, dict):
        raise ValueError("event file must contain one JSON object")
    event = cast(JsonObject, value)
    event_id = require_string(event, "event_id", str(arguments.event))
    candidate_id = require_string(event, "candidate_id", str(arguments.event))
    label_kind = require_string(event, "label_kind", str(arguments.event))
    if label_kind not in {"pair", "report", "operation"}:
        raise ValueError("label_kind must be pair, report, or operation")
    if not isinstance(event.get("judgment"), dict):
        raise ValueError("judgment must be an object")
    require_string(event, "reader", str(arguments.event))
    if arguments.ledger == "llm":
        require_string(event, "model", str(arguments.event))
        require_string(event, "prompt_version", str(arguments.event))

    candidate_path = config.workspace / "select_label_candidates" / f"{label_kind}s.jsonl"
    if label_kind == "report":
        candidate_path = config.workspace / "select_label_candidates" / "reports.jsonl"
    if not candidate_path.is_file():
        raise FileNotFoundError(f"candidate selection has not produced {candidate_path}")
    candidates = {str(row["candidate_id"]): row for _line, row in read_jsonl(candidate_path) if "candidate_id" in row}
    candidate = candidates.get(candidate_id)
    if candidate is None or candidate.get("label_kind") != label_kind:
        raise ValueError(f"{candidate_id} is not a current {label_kind} candidate")
    candidate_revision = require_string(candidate, "candidate_revision", f"candidate {candidate_id}")
    supplied_revision = event.get("candidate_revision")
    if supplied_revision is not None and supplied_revision != candidate_revision:
        raise ValueError(f"{candidate_id} event has a stale candidate_revision")
    event["candidate_revision"] = candidate_revision

    event.setdefault("recorded_at", datetime.now(tz=UTC).isoformat())
    ledger_name = "llm_label_ledger" if arguments.ledger == "llm" else "human_label_ledger"
    ledger_path = config.source_path(ledger_name)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            existing = json.loads(stripped)
            if isinstance(existing, dict) and existing.get("event_id") == event_id:
                raise ValueError(f"{ledger_path}:{line_number}: event_id {event_id} already exists")
        handle.seek(0, os.SEEK_END)
        handle.write(canonical_json(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    print(f"appended {event_id} to {ledger_path}")


if __name__ == "__main__":
    main()
