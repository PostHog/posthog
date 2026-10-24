from __future__ import annotations

import os
import json
import shutil
import hashlib
import argparse
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import JsonValue

from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.escape_sql import escape_hogql_identifier, escape_hogql_string

from products.posthog_ai.eval_harness.environment.schema import EVENT_TABLE, METRIC_TABLE, EnvironmentEvent
from products.posthog_ai.eval_harness.environment.storage import file_sha256, require_private_path
from products.signals.backend.scout_harness.eval_environment.source_client import SourceAPI, SourceExportError
from products.signals.backend.scout_harness.eval_environment.source_context import SourceContext, canonical_digest
from products.signals.backend.scout_harness.eval_environment.source_plan import SourceSlicePlan


class SourceEvents:
    def __init__(self, api: SourceAPI, plan: SourceSlicePlan) -> None:
        self.api, self.plan = api, plan

    @staticmethod
    def _date(value: datetime) -> str:
        return "toDateTime64(" + escape_hogql_string(value.astimezone(UTC).isoformat()) + ", 6, 'UTC')"

    def predicate(self) -> str:
        windows = []
        for window in self.plan.event_windows:
            clauses = [
                "timestamp >= " + self._date(window.start),
                "timestamp < " + self._date(window.end),
                "event IN " + escape_hogql_string(tuple(window.events)),
            ]
            for prop in window.properties:
                clauses.append(
                    "properties."
                    + escape_hogql_identifier(prop.name)
                    + " IN "
                    + escape_hogql_string(tuple(prop.values))
                )
            windows.append("(" + " AND ".join(clauses) + ")")
        return "(" + (" OR ".join(windows) or "false") + ") AND created_at < " + self._date(self.plan.source_cutoff)

    def count(self) -> int:
        rows = self.api.query("SELECT count(), uniqExact(uuid) FROM events WHERE " + self.predicate())
        if len(rows) != 1 or len(rows[0]) != 2:
            raise SourceExportError("The source event count query returned an unexpected shape.")
        count, unique = rows[0]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0 or unique != count:
            raise SourceExportError("The selected source events contain duplicate identities or an invalid count.")
        if count > self.plan.max_events:
            raise SourceExportError(
                "The source slice exceeds max_events. Narrow the plan or raise its limit; no sampling was used."
            )
        return count

    @staticmethod
    def _timestamp(value: JsonValue) -> str:
        if not isinstance(value, str):
            raise SourceExportError("The event query returned a missing timestamp.")
        # This exporter selects toTimeZone(..., 'UTC') before toString, which omits the zone suffix.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC).isoformat() if parsed.tzinfo is None else parsed.astimezone(UTC).isoformat()

    def rows(self, expected_count: int) -> Iterator[EnvironmentEvent]:
        cursor: tuple[datetime, str] | None = None
        seen: set[UUID] = set()
        while len(seen) < expected_count:
            where = self.predicate()
            if cursor:
                where += (
                    " AND (timestamp, toString(uuid)) > ("
                    + self._date(cursor[0])
                    + ", "
                    + escape_hogql_string(cursor[1])
                    + ")"
                )
            query = (
                "SELECT toString(uuid), toString(toTimeZone(timestamp, 'UTC')), event, distinct_id, "
                "toString(event_person_id), properties, toString(toTimeZone(created_at, 'UTC')) "
                "FROM events WHERE " + where + " ORDER BY timestamp, toString(uuid) LIMIT " + str(self.plan.page_size)
            )
            page = self.api.query(query)
            if not page:
                raise SourceExportError("The source query ended before every selected event was exported.")
            for row in page:
                if len(row) != 7:
                    raise SourceExportError("The source event query returned an unexpected row shape.")
                event = EnvironmentEvent.model_validate(
                    dict(
                        zip(
                            ("uuid", "timestamp", "event", "distinct_id", "person_id", "properties", "created_at"),
                            (row[0], self._timestamp(row[1]), row[2], row[3], row[4], row[5], self._timestamp(row[6])),
                            strict=True,
                        )
                    )
                )
                next_cursor = event.timestamp, str(event.uuid)
                if event.uuid in seen or (cursor is not None and next_cursor <= cursor):
                    raise SourceExportError("The source event query returned repeated or unordered rows.")
                if event.timestamp >= self.plan.source_cutoff or event.created_at >= self.plan.source_cutoff:
                    raise SourceExportError("A source event is outside the export cutoff.")
                if not any(
                    window.start <= event.timestamp < window.end and event.event in window.events
                    for window in self.plan.event_windows
                ):
                    raise SourceExportError("A source event is outside the selected names and time windows.")
                seen.add(event.uuid)
                if len(seen) > expected_count:
                    raise SourceExportError("The selected source events changed while exporting.")
                cursor = next_cursor
                yield event


class SourceEnvironmentExporter:
    def __init__(self, api: SourceAPI, plan: SourceSlicePlan) -> None:
        if api.project_path != f"/api/projects/{plan.project_id}/":
            raise SourceExportError("The source client and slice plan select different projects.")
        self.api, self.plan = api, plan

    @staticmethod
    def _write_json(path: Path, value: JsonValue) -> None:
        with path.open("x", encoding="utf-8") as output:
            path.chmod(0o600)
            output.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")

    @staticmethod
    def _row_digest(row: EnvironmentEvent) -> bytes:
        return (json.dumps(row.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n").encode()

    def export(self, output: Path) -> dict[str, JsonValue]:
        self.plan.assert_current(datetime.now(UTC))
        output = require_private_path(output)
        if output.exists():
            raise FileExistsError("The source export destination already exists; use a new private directory.")
        # Validate context and unsupported dependencies before downloading event data or publishing files.
        snapshot = SourceContext(self.api, self.plan).read() if self.plan.purpose == "scout" else None
        events = SourceEvents(self.api, self.plan)
        count = events.count() if self.plan.event_windows else 0
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".scout-source-", dir=output.parent) as temporary:
            folder = Path(temporary)
            event_path = folder / "events.parquet"
            digest = hashlib.sha256()

            def rows() -> Iterator[EnvironmentEvent]:
                for row in events.rows(count):
                    digest.update(self._row_digest(row))
                    yield row

            EVENT_TABLE.write(event_path, rows())
            event_path.chmod(0o600)
            METRIC_TABLE.write(folder / "metrics.parquet", snapshot.metrics if snapshot else [])
            (folder / "metrics.parquet").chmod(0o600)
            # Two complete reads detect edits as well as additions/deletions while collecting the slice.
            verified_count = events.count() if self.plan.event_windows else 0
            verified_digest = hashlib.sha256()
            for row in events.rows(verified_count):
                verified_digest.update(self._row_digest(row))
            if verified_count != count or verified_digest.digest() != digest.digest():
                raise SourceExportError("Source events changed during export; retry with a fresh cutoff and output.")
            verified_snapshot = SourceContext(self.api, self.plan).read() if snapshot else None
            if verified_snapshot != snapshot:
                raise SourceExportError(
                    "Source Scout context changed during export; retry with a fresh cutoff and output."
                )
            if snapshot:
                self._write_json(folder / "case.json", snapshot.case.model_dump(mode="json"))
            self._write_json(folder / "source-plan.json", self.plan.model_dump(mode="json"))
            provenance: dict[str, JsonValue] = {
                "schema_version": 1,
                "mode": "source",
                "purpose": self.plan.purpose,
                "runnable_scout": snapshot is not None,
                "source_origin": self.api.origin,
                "project_id": self.plan.project_id,
                "source_cutoff": self.plan.source_cutoff.isoformat(),
                "event_count": count,
                "metric_count": len(snapshot.metrics) if snapshot else 0,
                "context_count": len(snapshot.case.state.records()) if snapshot else 0,
                "event_rows_sha256": digest.hexdigest(),
                "context_sha256": canonical_digest(snapshot.model_dump(mode="json")) if snapshot else None,
                "identity_mappings": dict(snapshot.identity_mappings) if snapshot else {},
                "profile_snapshot_sha256": file_sha256(require_private_path(self.plan.profile_snapshot))
                if self.plan.profile_snapshot
                else None,
                "source_reads": self.api.read_count,
                "validation": "two complete matching live reads plus an explicitly supplied current profile snapshot; no cross-database atomic snapshot claimed",
                "synthetic_rows": 0,
                "files": {path.name: file_sha256(path) for path in sorted(folder.iterdir())},
            }
            self._write_json(folder / "source-provenance.json", provenance)
            # Reserve the destination atomically: never replace a concurrent export or existing files.
            output.mkdir(mode=0o700)
            try:
                for path in folder.iterdir():
                    os.link(path, output / path.name)
            except BaseException:
                shutil.rmtree(output)
                raise
        return provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a real project slice without source mutations or model calls.")
    parser.add_argument("--source", required=True, help="PostHog source origin")
    parser.add_argument("--token-env", required=True, help="Environment variable holding a read-only API token")
    parser.add_argument("--plan", required=True, type=Path, help="Private explicit source selection plan")
    parser.add_argument("--output", required=True, type=Path, help="New private output directory")
    args = parser.parse_args(argv)
    os.umask(0o077)
    api = None
    try:
        plan = SourceSlicePlan.model_validate_json(require_private_path(args.plan).read_bytes())
        api = SourceAPI(args.source, token_env=args.token_env, project_id=plan.project_id)
        result = SourceEnvironmentExporter(api, plan).export(args.output)
        print(json.dumps({"output": str(args.output), "events": result["event_count"], "paid_calls": 0}))  # noqa: T201
        return 0
    except (ValueError, OSError, BaseHogQLError) as error:
        # Validation errors can include source data values, so only deliberate operational messages are printed.
        message = (
            str(error) if isinstance(error, SourceExportError) else "Source export failed validation or file access."
        )
        print(message)  # noqa: T201
        return 2
    finally:
        if api is not None:
            api.close()


if __name__ == "__main__":
    raise SystemExit(main())
