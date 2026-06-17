"""Seed the engineering analytics warehouse tables from the checked-in GitHub fixture.

Loads ``products/engineering_analytics/fixtures/github_pull_requests.json`` and
``github_workflow_runs.json`` (a real PostHog/posthog snapshot captured with
``fixtures/fetch.py``) into the team's data warehouse behind a connected GitHub
source, exactly as a real sync would: a GitHub ``ExternalDataSource`` with a
``--prefix``, plus ``pull_requests`` / ``workflow_runs`` ``ExternalDataSchema`` rows
pointing at the materialized ``<prefix>github_pull_requests`` /
``<prefix>github_workflow_runs`` tables. The product resolves those names per team
(``logic.sources``), so seeding under a non-default prefix exercises the resolver
rather than the old hardcoded ``github_*`` names.

Timestamps are rebased so the newest fixture row lands at "now" — the queries
window on server-side now(), so an unshifted old snapshot would render empty.
Pass --keep-dates for the faithful snapshot instead.

Re-running replaces this seed source's tables, but a table owned by a different
(real) connected source is never touched. Local/dev only: requires the dev object
storage and ClickHouse from the hogli stack.

Usage:
    python manage.py seed_engineering_analytics --team-id 1
    python manage.py seed_engineering_analytics --team-id 1 --prefix devex_eng_analytics
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

from products.data_warehouse.backend.types import ExternalDataSourceType
from products.engineering_analytics.backend.logic.sources import PULL_REQUESTS_SCHEMA, WORKFLOW_RUNS_SCHEMA
from products.engineering_analytics.backend.logic.views.source_schema import (
    PULL_REQUESTS_COLUMNS,
    WORKFLOW_RUNS_COLUMNS,
)
from products.warehouse_sources.backend.models.credential import get_or_create_datawarehouse_credential
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.table import DataWarehouseTable
from products.warehouse_sources.backend.models.util import validate_source_prefix

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures"

PR_DATE_FIELDS = ("created_at", "updated_at", "merged_at", "closed_at")
RUN_DATE_FIELDS = ("created_at", "run_started_at", "updated_at")

# Marks the GitHub source this command owns, so re-seeding never clobbers a real source.
SEED_SOURCE_ID = "engineering_analytics_seed"
# Default prefix is non-trivial on purpose: it proves the product resolves the real
# per-team table name rather than assuming the bare ``github_*`` names.
DEFAULT_PREFIX = "eng_analytics_seed"


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
    help = "Seed the engineering analytics warehouse tables behind a connected GitHub source from the fixture."

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
        parser.add_argument(
            "--prefix",
            type=str,
            default=DEFAULT_PREFIX,
            help="Source prefix for the seeded GitHub tables (table name is <prefix>github_<endpoint>).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=True (local/dev only).")
        if not settings.OBJECT_STORAGE_ENABLED or not settings.OBJECT_STORAGE_ACCESS_KEY_ID:
            raise CommandError("Object storage is not configured — start the dev stack first (hogli start).")
        prefix = options["prefix"]
        prefix_valid, prefix_error = validate_source_prefix(prefix)
        if not prefix_valid:
            raise CommandError(f"Invalid --prefix {prefix!r}: {prefix_error}")
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
            source = self._get_or_create_seed_source(team, prefix)
            self._upsert_schema_table(
                team, source, credential, prefix, PULL_REQUESTS_SCHEMA, PULL_REQUESTS_COLUMNS, map(_flatten_pr, prs)
            )
            self._upsert_schema_table(
                team, source, credential, prefix, WORKFLOW_RUNS_SCHEMA, WORKFLOW_RUNS_COLUMNS, map(_flatten_run, runs)
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(prs)} pull requests and {len(runs)} workflow runs into team {team.pk} "
                f"under GitHub source prefix '{prefix}'."
            )
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

    def _get_or_create_seed_source(self, team: Team, prefix: str) -> ExternalDataSource:
        source = ExternalDataSource.objects.filter(
            team=team, source_id=SEED_SOURCE_ID, source_type=ExternalDataSourceType.GITHUB
        ).first()
        if source is None:
            return ExternalDataSource.objects.create(
                team=team,
                source_id=SEED_SOURCE_ID,
                connection_id=SEED_SOURCE_ID,
                status=ExternalDataSource.Status.COMPLETED,
                source_type=ExternalDataSourceType.GITHUB,
                prefix=prefix,
            )
        if source.prefix != prefix:
            source.prefix = prefix
            source.save(update_fields=["prefix", "updated_at"])
        return source

    def _upsert_schema_table(
        self,
        team: Team,
        source: ExternalDataSource,
        credential: Any,
        prefix: str,
        schema_name: str,
        columns: dict[str, dict[str, str]],
        rows: Any,
    ) -> None:
        records = list(rows)
        # The materialized table name is exactly what a real sync produces: <prefix>github_<endpoint>.
        table_name = f"{prefix}github_{schema_name}"
        headers = list(columns.keys())
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows([record[header] for header in headers] for record in records)

        s3_prefix = f"data-warehouse/engineering_analytics_{table_name}/team_{team.pk}"
        object_storage.write(f"{s3_prefix}/{table_name}.csv", output.getvalue())
        url_pattern = f"{_warehouse_endpoint()}/{settings.OBJECT_STORAGE_BUCKET}/{s3_prefix}/*.csv"

        existing = DataWarehouseTable.objects.filter(team=team, name=table_name).first()
        if existing is not None and existing.external_data_source_id not in (None, source.id):
            raise CommandError(
                f"Table {table_name} belongs to another warehouse source — refusing to overwrite it. "
                "Use a different --prefix (or another team) to seed fixture data."
            )
        if existing is not None:
            existing.format = DataWarehouseTable.TableFormat.CSVWithNames
            existing.url_pattern = url_pattern
            existing.credential = credential
            existing.external_data_source = source
            existing.columns = columns
            existing.options = {**(existing.options or {}), "csv_allow_double_quotes": True}
            existing.deleted = False
            existing.deleted_at = None
            existing.save()
            table = existing
        else:
            table = DataWarehouseTable.objects.create(
                team=team,
                name=table_name,
                format=DataWarehouseTable.TableFormat.CSVWithNames,
                url_pattern=url_pattern,
                credential=credential,
                external_data_source=source,
                columns=columns,
                options={"csv_allow_double_quotes": True},
            )

        schema = ExternalDataSchema.objects.filter(team=team, source=source, name=schema_name).first()
        if schema is None:
            ExternalDataSchema.objects.create(team=team, source=source, name=schema_name, table=table, should_sync=True)
        elif schema.table_id != table.id or not schema.should_sync or schema.deleted:
            schema.table = table
            schema.should_sync = True
            schema.deleted = False
            schema.deleted_at = None
            schema.save()
        self.stdout.write(f"Seeded warehouse table {table_name} ({len(records)} rows) as schema '{schema_name}'.")
