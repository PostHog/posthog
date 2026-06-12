"""Seed the engineering analytics warehouse tables from the checked-in GitHub fixture.

Loads ``products/engineering_analytics/fixtures/github_pull_requests.json`` and
``github_workflow_runs.json`` (a real PostHog/posthog snapshot captured with
``fixtures/fetch.py``) into the team's data warehouse as the
``github_pull_requests`` and ``github_workflow_runs`` tables the product queries.

Timestamps are rebased so the newest fixture row lands at "now" — the queries
window on server-side now(), so an unshifted old snapshot would render empty.
Pass --keep-dates for the faithful snapshot instead.

Re-running replaces previously seeded tables, but tables owned by a connected
GitHub warehouse source are never touched. Local/dev only: requires the dev
object storage and ClickHouse from the hogli stack.

Usage:
    python manage.py seed_engineering_analytics --team-id 1
    python manage.py seed_engineering_analytics --team-id 1 --keep-dates
"""

import csv
import json
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.models.credential import get_or_create_datawarehouse_credential
from products.warehouse_sources.backend.models.table import DataWarehouseTable

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures"

PR_DATE_FIELDS = ("created_at", "updated_at", "merged_at", "closed_at")
RUN_DATE_FIELDS = ("created_at", "run_started_at", "updated_at")


def _flatten_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: pr[key] for key in PULL_REQUESTS_COLUMNS if key not in ("user", "head", "base", "labels", "draft")},
        "draft": int(bool(pr["draft"])),
        "user": json.dumps(pr["user"]),
        "head": json.dumps(pr["head"]),
        "base": json.dumps(pr["base"]),
        "labels": json.dumps(pr["labels"]),
    }


def _flatten_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: run[key] for key in WORKFLOW_RUNS_COLUMNS if key != "repository"},
        "repository": json.dumps(run["repository"]),
    }


def _warehouse_endpoint() -> str:
    # ClickHouse runs in docker, so a localhost object-storage endpoint must be
    # rewritten to the docker host (same approach as the demo data generator).
    endpoint = settings.OBJECT_STORAGE_ENDPOINT.rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return endpoint
    netloc = f"host.docker.internal:{parsed.port}" if parsed.port else "host.docker.internal"
    return urlunparse(parsed._replace(netloc=netloc))


class Command(BaseCommand):
    help = "Seed the engineering analytics github_pull_requests/github_workflow_runs warehouse tables from the fixture."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--team-id", type=int, required=True, help="Team to seed the warehouse tables into.")
        parser.add_argument(
            "--fixture-dir", type=Path, default=FIXTURE_DIR, help="Directory holding the fixture JSON files."
        )
        parser.add_argument(
            "--keep-dates",
            action="store_true",
            help="Load the snapshot's original timestamps instead of rebasing them to now.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True (local/dev only).")
        if not settings.OBJECT_STORAGE_ENABLED or not settings.OBJECT_STORAGE_ACCESS_KEY_ID:
            raise CommandError("Object storage is not configured — start the dev stack first (hogli start).")
        try:
            team = Team.objects.get(pk=options["team_id"])
        except Team.DoesNotExist:
            raise CommandError(f"Team {options['team_id']} does not exist.")

        prs = self._load_fixture(options["fixture_dir"], "github_pull_requests.json")
        runs = self._load_fixture(options["fixture_dir"], "github_workflow_runs.json")

        # Always normalize timestamps to a ClickHouse-friendly format; rebasing is optional.
        shift = timedelta(0) if options["keep_dates"] else self._rebase_delta(prs, runs)
        prs = [self._shift_dates(pr, PR_DATE_FIELDS, shift) for pr in prs]
        runs = [self._shift_dates(run, RUN_DATE_FIELDS, shift) for run in runs]
        if shift:
            self.stdout.write(f"Rebased timestamps forward by {shift}.")

        with team_scope(team.pk):
            credential = get_or_create_datawarehouse_credential(
                team_id=team.pk,
                access_key=settings.OBJECT_STORAGE_ACCESS_KEY_ID,
                access_secret=settings.OBJECT_STORAGE_SECRET_ACCESS_KEY,
            )
            self._upsert_table(team, credential, "github_pull_requests", PULL_REQUESTS_COLUMNS, map(_flatten_pr, prs))
            self._upsert_table(team, credential, "github_workflow_runs", WORKFLOW_RUNS_COLUMNS, map(_flatten_run, runs))

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(prs)} pull requests and {len(runs)} workflow runs into team {team.pk}.")
        )

    def _load_fixture(self, fixture_dir: Path, filename: str) -> list[dict[str, Any]]:
        path = fixture_dir / filename
        if not path.exists():
            raise CommandError(
                f"Fixture {path} not found — run products/engineering_analytics/fixtures/fetch.py first."
            )
        return json.loads(path.read_text())

    def _rebase_delta(self, prs: list[dict[str, Any]], runs: list[dict[str, Any]]) -> timedelta:
        newest = max(
            datetime.fromisoformat(row[field])
            for row, fields in [*((pr, PR_DATE_FIELDS) for pr in prs), *((run, RUN_DATE_FIELDS) for run in runs)]
            for field in fields
            if row[field] is not None
        )
        return max(timedelta(0), timezone.now() - newest)

    def _shift_dates(self, row: dict[str, Any], fields: tuple[str, ...], shift: timedelta) -> dict[str, Any]:
        shifted = dict(row)
        for field in fields:
            if shifted[field] is not None:
                moved = datetime.fromisoformat(shifted[field]) + shift
                shifted[field] = moved.strftime("%Y-%m-%d %H:%M:%S")
        return shifted

    def _upsert_table(
        self,
        team: Team,
        credential: Any,
        name: str,
        columns: dict[str, dict[str, str]],
        rows: Any,
    ) -> None:
        records = list(rows)
        headers = list(columns.keys())
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows([record[header] for header in headers] for record in records)

        s3_prefix = f"data-warehouse/engineering_analytics_{name}/team_{team.pk}"
        object_storage.write(f"{s3_prefix}/{name}.csv", output.getvalue())
        url_pattern = f"{_warehouse_endpoint()}/{settings.OBJECT_STORAGE_BUCKET}/{s3_prefix}/*.csv"

        existing = DataWarehouseTable.objects.filter(team=team, name=name).first()
        if existing is not None and existing.external_data_source is not None:
            raise CommandError(
                f"Table {name} belongs to a connected warehouse source — refusing to overwrite it. "
                "Delete the source (or use another team) to seed fixture data."
            )
        if existing is not None:
            existing.format = DataWarehouseTable.TableFormat.CSVWithNames
            existing.url_pattern = url_pattern
            existing.credential = credential
            existing.columns = columns
            existing.options = {**(existing.options or {}), "csv_allow_double_quotes": True}
            existing.deleted = False
            existing.deleted_at = None
            existing.save()
        else:
            DataWarehouseTable.objects.create(
                team=team,
                name=name,
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                url_pattern=url_pattern,
                credential=credential,
                columns=columns,
                options={"csv_allow_double_quotes": True},
            )
        self.stdout.write(f"Created warehouse table {name} ({len(records)} rows).")
