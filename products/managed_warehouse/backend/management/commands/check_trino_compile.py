"""Report which of a team's models would fail the Trino shadow build's compile step, in seconds. Read-only.

    python manage.py check_trino_compile --team-id 2
    python manage.py check_trino_compile --team-id 2 --explain
    python manage.py check_trino_compile --team-id 2 --saved-query-ids <uuid>,<uuid> --format json

Exits non-zero when any model fails.
"""

import sys
import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models import Team

from products.managed_warehouse.backend.trino_compile_check import TrinoCompileCheckReport, check_trino_compile


class Command(BaseCommand):
    help = "Compile a team's saved queries for Trino as the shadow build does, and optionally EXPLAIN them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, required=True)
        parser.add_argument("--saved-query-ids", help="Comma-separated saved query UUIDs. Defaults to all.")
        parser.add_argument("--explain", action="store_true", help="Also send EXPLAIN to the team's Trino.")
        parser.add_argument("--limit", type=int, help="Check at most this many saved queries.")
        parser.add_argument("--format", choices=["table", "json"], default="table")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist")
        ids = options["saved_query_ids"]
        report = check_trino_compile(
            team,
            saved_query_ids=[value.strip() for value in ids.split(",") if value.strip()] if ids else None,
            explain=options["explain"],
            limit=options["limit"],
        )
        if options["format"] == "json":
            self.stdout.write(json.dumps(_as_json(report), indent=2))
        else:
            self._write_table(report)
        if report.ok_count < len(report.rows):
            sys.exit(1)

    def _write_table(self, report: TrinoCompileCheckReport) -> None:
        for row in report.rows:
            status = "ok" if row.ok else "failed"
            line = f"{status:<6} {row.stage:<7} {row.saved_query_id}  {row.name}"
            if not row.ok:
                line += f"  {row.error_code}: {row.message}"
            self.stdout.write(line)
        self.stdout.write("")
        for code, count in report.error_counts.items():
            self.stdout.write(f"{count:>5}  {code}")
        self.stdout.write(f"{report.ok_count}/{len(report.rows)} ok")


def _as_json(report: TrinoCompileCheckReport) -> dict[str, Any]:
    return {
        "rows": [
            {
                "saved_query_id": row.saved_query_id,
                "name": row.name,
                "stage": row.stage.value,
                "status": "ok" if row.ok else "failed",
                "error_code": row.error_code,
                "message": row.message,
            }
            for row in report.rows
        ],
        "error_counts": report.error_counts,
        "ok": report.ok_count,
        "total": len(report.rows),
    }
