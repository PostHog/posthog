from __future__ import annotations

import hashlib
from pathlib import Path

from ..io import JsonObject, read_jsonl, require_string, write_json, write_jsonl
from ..stage import StageContext

SIGNATURE_FIELDS = {
    "polarity",
    "surface",
    "failure_mode",
    "error_anchor",
    "affected_entity",
    "concern_tags",
    "one_liner",
}


class EnrichConcerns:
    name = "enrich_concerns"

    def input_paths(self, context: StageContext) -> list[Path]:
        return [
            context.stage_dir("import_export") / "signals.jsonl",
            context.config.source_path("concern_ledger"),
        ]

    def output_paths(self, context: StageContext) -> list[Path]:
        directory = context.stage_dir(self.name)
        return [directory / "signals.jsonl", directory / "requests.jsonl", directory / "summary.json"]

    def config_fragment(self, context: StageContext) -> JsonObject:
        prompt_version = context.config.source.get("concern_prompt_version")
        if not isinstance(prompt_version, str) or not prompt_version:
            raise ValueError("source.concern_prompt_version must be a non-empty string")
        return {
            "prompt_version": prompt_version,
            "ledger_policy": "append-only; last content-matching event wins",
            "provider_calls": "outside orchestrator",
        }

    def run(self, context: StageContext) -> None:
        signals_path, ledger_path = self.input_paths(context)
        ledger: dict[tuple[str, str], JsonObject] = {}
        ledger_documents: set[str] = set()
        ledger_events = 0
        superseded_events = 0
        event_ids: set[str] = set()
        if ledger_path.exists():
            for line_number, row in read_jsonl(ledger_path):
                location = f"{ledger_path}:{line_number}"
                event_id = require_string(row, "event_id", location)
                if event_id in event_ids:
                    raise ValueError(f"{location}: duplicate event_id {event_id}")
                event_ids.add(event_id)
                document_id = require_string(row, "document_id", location)
                content_sha256 = require_string(row, "content_sha256", location)
                key = (document_id, content_sha256)
                if key in ledger:
                    superseded_events += 1
                ledger[key] = row
                ledger_documents.add(document_id)
                ledger_events += 1

        enriched: list[JsonObject] = []
        requests: list[JsonObject] = []
        ledger_hits = 0
        supplied = 0
        stale_events = 0
        prompt_version = str(context.config.source["concern_prompt_version"])
        for line_number, source in read_jsonl(signals_path):
            row = dict(source)
            document_id = require_string(row, "document_id", f"{signals_path}:{line_number}")
            content = require_string(row, "content", f"{signals_path}:{line_number}")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            has_complete_enrichment = all(
                row.get(field) is not None
                for field in ("embedding", "concern_signature", "concern_signature_embedding")
            )
            if has_complete_enrichment:
                supplied += 1
                enriched.append(row)
                continue

            event = ledger.get((document_id, content_hash))
            if event is None and document_id in ledger_documents:
                stale_events += 1
            if event is not None:
                for field in ("embedding", "concern_signature", "concern_signature_embedding"):
                    if row.get(field) is None and event.get(field) is not None:
                        row[field] = event[field]
                ledger_hits += 1

            missing = [
                field
                for field in ("embedding", "concern_signature", "concern_signature_embedding")
                if row.get(field) is None
            ]
            if missing:
                signature = row.get("concern_signature")
                requests.append(
                    {
                        "request_id": f"concern:{document_id}:{content_hash[:16]}",
                        "document_id": document_id,
                        "content_sha256": content_hash,
                        "prompt_version": prompt_version,
                        "missing": missing,
                        "source_product": row.get("source_product"),
                        "source_type": row.get("source_type"),
                        "content": content,
                        "concern_signature": signature,
                        "required_signature_fields": sorted(SIGNATURE_FIELDS),
                    }
                )
            enriched.append(row)

        directory = context.stage_dir(self.name)
        write_jsonl(directory / "signals.jsonl", enriched)
        write_jsonl(directory / "requests.jsonl", requests)
        write_json(
            directory / "summary.json",
            {
                "signals": len(enriched),
                "supplied_complete": supplied,
                "ledger_events": ledger_events,
                "ledger_hits": ledger_hits,
                "superseded_events": superseded_events,
                "stale_content_events": stale_events,
                "pending_requests": len(requests),
            },
        )
        if requests:
            raise RuntimeError(
                f"{len(requests)} signals still need enrichment; fulfill {directory / 'requests.jsonl'} "
                f"by appending content-matching events to {ledger_path}, then resume"
            )
