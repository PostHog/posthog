"""Report which of a team's models would fail the Trino shadow build's compile step. Read-only.

    python manage.py check_trino_compile --team-id 2
    python manage.py check_trino_compile --team-id 2 --explain --output /tmp/team2.jsonl
    python manage.py check_trino_compile --team-id 2 --saved-query-ids <uuid>,<uuid> --format json

Each model's result is written as soon as it is checked. With --output, rows are appended to a JSON lines
file, and a rerun with the same file skips the models it already holds, so an interrupted run resumes.
Exits non-zero when any model fails.
"""

import sys
import json
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from products.managed_warehouse.backend.trino_compile_check import (
    TrinoCompileCheckReport,
    TrinoCompileCheckRow,
    TrinoCompileCheckStage,
    check_trino_compile,
)
from products.managed_warehouse.backend.trino_compiler import TrinoTargetUnavailable


class Command(BaseCommand):
    help = "Compile a team's saved queries for Trino as the shadow build does, and optionally EXPLAIN them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--saved-query-ids", help="Comma-separated saved query UUIDs. Defaults to all.")
        parser.add_argument("--explain", action="store_true", help="Also send EXPLAIN to the team's Trino.")
        parser.add_argument("--limit", type=int, help="Check at most this many saved queries.")
        parser.add_argument("--format", choices=["table", "json"], default="table")
        parser.add_argument(
            "--output", type=Path, help="Append each row to this JSON lines file and skip rows it already holds."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")
        ids = options["saved_query_ids"]
        output: Path | None = options["output"]
        previous = _read_rows(output) if output is not None and output.exists() else []
        if options["explain"]:
            # A row that only compiled has not been planned yet, so an explain run checks it again.
            previous = [row for row in previous if not (row.ok and row.stage == TrinoCompileCheckStage.COMPILE)]
        rows = list(previous)
        sink = output.open("a") if output is not None else None
        try:
            for row in check_trino_compile(
                team,
                saved_query_ids=[value.strip() for value in ids.split(",") if value.strip()] if ids else None,
                explain=options["explain"],
                limit=options["limit"],
                skip_ids=[row.saved_query_id for row in previous],
            ):
                rows.append(row)
                if sink is not None:
                    sink.write(json.dumps(row.to_json()) + "\n")
                    sink.flush()
                self._write_row(row, options["format"])
        except TrinoTargetUnavailable as error:
            raise CommandError(f"No Trino target for team {team.pk}, nothing was checked: {error}") from error
        finally:
            if sink is not None:
                sink.close()
        report = TrinoCompileCheckReport(rows=tuple(rows))
        self._write_summary(report, options["format"])
        if report.ok_count < len(report.rows):
            sys.exit(1)

    def _write_row(self, row: TrinoCompileCheckRow, output_format: str) -> None:
        if output_format == "json":
            self.stdout.write(json.dumps(row.to_json()))
        else:
            line = f"{'ok' if row.ok else 'failed':<6} {row.stage:<7} {row.saved_query_id}  {row.name}"
            if not row.ok:
                line += f"  {row.error_code}: {row.message}"
            self.stdout.write(line)
        self.stdout.flush()

    def _write_summary(self, report: TrinoCompileCheckReport, output_format: str) -> None:
        if output_format == "json":
            summary = {"error_counts": report.error_counts, "ok": report.ok_count, "total": len(report.rows)}
            self.stdout.write(json.dumps({"summary": summary}))
            return
        self.stdout.write("")
        for code, count in report.error_counts.items():
            self.stdout.write(f"{count:>5}  {code}")
        self.stdout.write(f"{report.ok_count}/{len(report.rows)} ok")


def _read_rows(path: Path) -> list[TrinoCompileCheckRow]:
    rows: dict[str, TrinoCompileCheckRow] = {}
    data = path.read_bytes()
    lines = data.split(b"\n")
    offset = 0
    for index, raw in enumerate(lines):
        end = offset + len(raw) + 1
        if raw.strip():
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                if index != len(lines) - 1:
                    raise
                # An interrupted write leaves a partial last record. Cut only that record off, in place.
                with path.open("r+b") as handle:
                    handle.truncate(offset)
                return list(rows.values())
            # A model checked again later, such as by an explain run, keeps only its latest row.
            rows[record["saved_query_id"]] = TrinoCompileCheckRow(
                saved_query_id=record["saved_query_id"],
                name=record["name"],
                stage=TrinoCompileCheckStage(record["stage"]),
                error_code=record["error_code"],
                message=record["message"],
                upstream_saved_query_id=record.get("upstream_saved_query_id"),
            )
        offset = end
    if data and not data.endswith(b"\n"):
        # A complete last record without its newline would join the next appended row.
        with path.open("ab") as handle:
            handle.write(b"\n")
    return list(rows.values())
