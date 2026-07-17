from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import cast

from ..io import JsonObject, read_jsonl, require_string, write_json, write_jsonl
from ..stage import StageContext


class NormalizeLabelLedgers:
    name = "normalize_label_ledgers"

    def input_paths(self, context: StageContext) -> list[Path]:
        candidates = context.stage_dir("select_label_candidates")
        return [
            candidates / "pairs.jsonl",
            candidates / "reports.jsonl",
            candidates / "operations.jsonl",
            context.config.source_path("llm_label_ledger"),
            context.config.source_path("human_label_ledger"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [
            directory / "pairs.jsonl",
            directory / "reports.jsonl",
            directory / "operations.jsonl",
            directory / "audit.jsonl",
            directory / "summary.json",
        ]

    def config_fragment(self, context: StageContext) -> JsonObject:
        required = context.config.labeling.get("required_label_kinds")
        if not isinstance(required, list) or any(value not in {"pair", "report", "operation"} for value in required):
            raise ValueError("labeling.required_label_kinds must be an array of pair, report, and/or operation")
        return {
            "ledger_policy": "append-only events; every applicable event is preserved",
            "required_label_kinds": required,
        }

    def run(self, context: StageContext) -> None:
        candidate_paths = self.input_paths(context)[:3]
        candidates: dict[str, JsonObject] = {}
        candidate_counts: Counter[str] = Counter()
        for path in candidate_paths:
            for line_number, row in read_jsonl(path):
                location = f"{path}:{line_number}"
                candidate_id = require_string(row, "candidate_id", location)
                if candidate_id in candidates:
                    raise ValueError(f"{location}: duplicate candidate_id {candidate_id}")
                kind = require_string(row, "label_kind", location)
                candidates[candidate_id] = row
                candidate_counts[kind] += 1

        normalized: dict[str, list[JsonObject]] = {"pair": [], "report": [], "operation": []}
        audit: list[JsonObject] = []
        event_ids: set[str] = set()
        judged_candidates: dict[str, set[str]] = {kind: set() for kind in normalized}
        ledger_counts: Counter[str] = Counter()
        for ledger_kind, path in (
            ("llm", context.config.source_path("llm_label_ledger")),
            ("human", context.config.source_path("human_label_ledger")),
        ):
            if not path.exists():
                continue
            for line_number, event in read_jsonl(path):
                location = f"{path}:{line_number}"
                event_id = require_string(event, "event_id", location)
                if event_id in event_ids:
                    raise ValueError(f"{location}: duplicate event_id {event_id}")
                event_ids.add(event_id)
                candidate_id = require_string(event, "candidate_id", location)
                candidate = candidates.get(candidate_id)
                if candidate is None:
                    raise ValueError(f"{location}: unknown or stale candidate_id {candidate_id}")
                candidate_revision = require_string(candidate, "candidate_revision", f"candidate {candidate_id}")
                event_revision = require_string(event, "candidate_revision", location)
                if event_revision != candidate_revision:
                    raise ValueError(f"{location}: candidate_revision does not match the current candidate")
                label_kind = require_string(event, "label_kind", location)
                if label_kind != candidate["label_kind"]:
                    raise ValueError(f"{location}: event label_kind does not match its candidate")
                judgment = event.get("judgment")
                if not isinstance(judgment, dict):
                    raise ValueError(f"{location}: judgment must be an object")
                row = self._normalize_event(
                    ledger_kind, event_id, candidate, event, cast(JsonObject, judgment), location
                )
                normalized[label_kind].append(row)
                judged_candidates[label_kind].add(candidate_id)
                ledger_counts[ledger_kind] += 1
                audit.append(
                    {
                        "event_id": event_id,
                        "candidate_id": candidate_id,
                        "candidate_revision": candidate_revision,
                        "label_kind": label_kind,
                        "ledger": ledger_kind,
                        "recorded_at": event.get("recorded_at"),
                        "normalized_provenance": row["provenance"],
                    }
                )

        directory = context.stage_dir(self.name)
        filenames = {"pair": "pairs.jsonl", "report": "reports.jsonl", "operation": "operations.jsonl"}
        for kind, filename in filenames.items():
            rows = sorted(normalized[kind], key=lambda row: str(row.get("operation_id", row)))
            write_jsonl(directory / filename, rows)
        write_jsonl(directory / "audit.jsonl", audit)
        summary = {
            "events": len(event_ids),
            "events_by_ledger": dict(sorted(ledger_counts.items())),
            "normalized_labels": {kind: len(rows) for kind, rows in normalized.items()},
            "candidates": dict(sorted(candidate_counts.items())),
            "judged_candidates": {kind: len(values) for kind, values in judged_candidates.items()},
            "unjudged_candidates": {kind: candidate_counts[kind] - len(judged_candidates[kind]) for kind in normalized},
            "unknown_becomes_negative": False,
        }
        write_json(directory / "summary.json", summary)

        required_value = context.config.labeling["required_label_kinds"]
        required = cast(list[str], required_value)
        missing = [kind for kind in required if not normalized[kind]]
        if missing:
            raise RuntimeError(
                f"no normalized labels for required kind(s) {', '.join(missing)}; review "
                f"{context.stage_dir('select_label_candidates') / 'llm_requests.jsonl'} and append judgments to "
                f"the configured LLM or human ledgers"
            )

    def _normalize_event(
        self,
        ledger_kind: str,
        event_id: str,
        candidate: JsonObject,
        event: JsonObject,
        judgment: JsonObject,
        location: str,
    ) -> JsonObject:
        confidence = judgment.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError(f"{location}: judgment.confidence must be in [0, 1]")
        reader = require_string(event, "reader", location)
        if ledger_kind == "llm":
            model = require_string(event, "model", location)
            prompt_version = require_string(event, "prompt_version", location)
            provenance = f"llm:{model}:{prompt_version}"
        else:
            provenance = f"human:{reader}"
        common: JsonObject = {
            "candidate_revision": candidate["candidate_revision"],
            "provenance": provenance,
            "confidence": float(confidence),
            "reader": reader,
            "rationale": judgment.get("rationale"),
            "raw_response_ref": event.get("raw_response_ref"),
        }
        kind = str(candidate["label_kind"])
        if kind == "pair":
            if not isinstance(judgment.get("same_concern"), bool):
                raise ValueError(f"{location}: pair judgment.same_concern must be boolean")
            return {
                **common,
                "signal_a": candidate["signal_a"],
                "signal_b": candidate["signal_b"],
                "same_concern": judgment["same_concern"],
            }
        if kind == "report":
            fields = ("coherent", "gold_positive", "known_overgroup", "components", "outcome")
            values = {field: judgment[field] for field in fields if field in judgment}
            if not values:
                raise ValueError(f"{location}: report judgment contains no report label")
            return {**common, "report_id": candidate["report_id"], **values}
        verdict = judgment.get("verdict")
        if verdict not in {"keep_separate", "whole_merge", "subset", "ambiguous"}:
            raise ValueError(f"{location}: invalid operation verdict {verdict!r}")
        fields = (
            "selected_left",
            "selected_right",
            "secondary_verdict",
            "secondary_selected_left",
            "secondary_selected_right",
            "secondary_reader",
        )
        values = {field: judgment[field] for field in fields if field in judgment}
        return {
            **common,
            "operation_id": event_id,
            "left_report_id": candidate["left_report_id"],
            "right_report_id": candidate["right_report_id"],
            "verdict": verdict,
            **values,
        }
