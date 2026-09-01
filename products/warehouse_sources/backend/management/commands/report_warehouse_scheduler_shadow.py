from collections import Counter
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

import psycopg

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models import ExternalDataJob
from products.warehouse_sources_queue.backend.sdk import SchedulerStateTable

TOP_OFFENDERS = 10


def parse_schedule_fired_at(schema_id: str, workflow_id: str | None) -> datetime | None:
    """Fire time of a schedule-fired run, or None for ad-hoc/manual runs.

    Temporal schedule-fired workflow ids look like ``{schema_id}-{ISO timestamp}``;
    anything else (manual triggers, backfills) carries no fire time.
    """
    prefix = f"{schema_id}-"
    if not workflow_id or not workflow_id.startswith(prefix):
        return None
    try:
        fired_at = datetime.fromisoformat(workflow_id[len(prefix) :])
    except ValueError:
        return None
    if fired_at.tzinfo is None:
        fired_at = fired_at.replace(tzinfo=UTC)
    return fired_at


def _print_offenders(stdout, label: str, schema_ids: list[str]) -> None:
    if not schema_ids:
        return
    stdout.write(f"  top {label} schemas:")
    for schema_id, count in Counter(schema_ids).most_common(TOP_OFFENDERS):
        stdout.write(f"    {schema_id}: {count}")


class Command(BaseCommand):
    help = "Compare shadow-scheduler would-fire decisions against actual ExternalDataJob rows"

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=float, default=24.0, help="Window to report over (default: 24)")
        parser.add_argument(
            "--since", type=str, default=None, help="Window start as an ISO timestamp (overrides --hours)"
        )
        parser.add_argument(
            "--tolerance-seconds",
            type=float,
            default=1800.0,
            help="Maximum distance between a decision's due time and a job for them to match (default: 1800)",
        )
        parser.add_argument("--team-id", type=int, default=None, help="Restrict the report to one team")

    def handle(self, *args, **options):
        if options["since"]:
            try:
                since = datetime.fromisoformat(options["since"])
            except ValueError as e:
                raise CommandError(f"--since is not a valid ISO timestamp: {e}")
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
        else:
            since = datetime.now(UTC) - timedelta(hours=options["hours"])
        tolerance = timedelta(seconds=options["tolerance_seconds"])

        with psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL) as conn:
            decisions = SchedulerStateTable.fetch_would_fires(conn, since)
        if options["team_id"] is not None:
            decisions = [d for d in decisions if d.team_id == options["team_id"]]

        jobs_qs = ExternalDataJob.objects.filter(created_at__gte=since - tolerance, schema_id__isnull=False)
        if options["team_id"] is not None:
            jobs_qs = jobs_qs.filter(team_id=options["team_id"])
        jobs = list(jobs_qs.values_list("schema_id", "workflow_id", "created_at"))

        # One-to-one greedy matching per schema, nearest job time to due time first.
        unmatched: dict[str, list[datetime]] = {}
        for decision in decisions:
            unmatched.setdefault(decision.schema_id, []).append(decision.due_at)

        matched = 0
        temporal_only: list[str] = []
        adhoc = 0
        for schema_uuid, workflow_id, created_at in jobs:
            schema_id = str(schema_uuid)
            fired_at = parse_schedule_fired_at(schema_id, workflow_id)
            schedule_fired = fired_at is not None
            job_time = fired_at if fired_at is not None else created_at
            candidates = unmatched.get(schema_id, [])
            best = min(candidates, key=lambda due: abs(due - job_time), default=None)
            if best is not None and abs(best - job_time) <= tolerance:
                candidates.remove(best)
                matched += 1
            elif schedule_fired:
                temporal_only.append(schema_id)
            else:
                # Unmatched runs with no parseable schedule id are manual or
                # backfill runs; count them but keep them out of the mismatch math.
                adhoc += 1

        shadow_only = [schema_id for schema_id, dues in unmatched.items() for _ in dues]

        self.stdout.write(f"window since {since.isoformat()} (tolerance {tolerance})")
        self.stdout.write(f"would_fire decisions: {len(decisions)}, jobs considered: {len(jobs)}")
        self.stdout.write(f"matched: {matched}")
        self.stdout.write(f"shadow_only (shadow would fire, no job): {len(shadow_only)}")
        self.stdout.write(f"temporal_only (schedule-fired job, no decision): {len(temporal_only)}")
        self.stdout.write(f"adhoc (manual/backfill runs, excluded): {adhoc}")
        _print_offenders(self.stdout, "shadow_only", shadow_only)
        _print_offenders(self.stdout, "temporal_only", temporal_only)
