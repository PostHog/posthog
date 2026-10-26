import time
from collections import Counter
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

import psycopg

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models import ExternalDataJob
from products.warehouse_sources.backend.scheduling.shadow import SYNC_EXTRACT_KIND
from products.warehouse_sources_queue.backend.sdk import SchedulerStateTable

TOP_OFFENDERS = 10
# A job older than this at the due time is treated as an orphaned RUNNING row,
# not as a run that Temporal's SKIP overlap policy waited for.
TEMPORAL_OVERLAP_MAX_JOB_AGE = timedelta(days=7)
EARLIER_JOBS_CHUNK_SIZE = 1000


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


def was_in_progress_at(
    due_at: datetime, intervals: list[tuple[datetime, datetime | None]], max_job_age: timedelta
) -> bool:
    """True when a job (created_at, finished_at) was in progress at ``due_at`` and
    was created no more than ``max_job_age`` before it."""
    return any(
        due_at - max_job_age <= created_at < due_at and (finished_at is None or finished_at > due_at)
        for created_at, finished_at in intervals
    )


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

        self.stderr.write(f"window since {since.isoformat()} (tolerance {tolerance})")

        self.stderr.write("fetching decisions...")
        started_at = time.monotonic()
        with psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL) as conn:
            decisions = SchedulerStateTable.fetch_would_fires(conn, SYNC_EXTRACT_KIND, since)
        if options["team_id"] is not None:
            decisions = [d for d in decisions if d.team_id == options["team_id"]]
        self.stderr.write(f"fetched {len(decisions)} decisions in {time.monotonic() - started_at:.1f}s")

        self.stderr.write("fetching jobs...")
        started_at = time.monotonic()
        match_start = since - tolerance
        jobs_qs = ExternalDataJob.objects.filter(created_at__gte=match_start, schema_id__isnull=False)
        if options["team_id"] is not None:
            jobs_qs = jobs_qs.filter(team_id=options["team_id"])
        jobs = list(jobs_qs.values_list("schema_id", "workflow_id", "created_at", "finished_at"))
        self.stderr.write(f"fetched {len(jobs)} jobs in {time.monotonic() - started_at:.1f}s")

        # One-to-one greedy matching per schema, nearest job time to due time first.
        unmatched: dict[str, list[datetime]] = {}
        for decision in decisions:
            unmatched.setdefault(decision.schedule_key, []).append(decision.due_at)

        matched = 0
        temporal_only: list[str] = []
        adhoc = 0
        job_intervals: dict[str, list[tuple[datetime, datetime | None]]] = {}
        started_at = time.monotonic()
        for job_index, (schema_uuid, workflow_id, created_at, finished_at) in enumerate(jobs, start=1):
            schema_id = str(schema_uuid)
            job_intervals.setdefault(schema_id, []).append((created_at, finished_at))
            fired_at = parse_schedule_fired_at(schema_id, workflow_id)
            if fired_at is None:
                # Runs with no parseable schedule id are manual or backfill
                # runs; never let them consume a shadow decision.
                adhoc += 1
            else:
                candidates = unmatched.get(schema_id, [])
                best = min(candidates, key=lambda due: abs(due - fired_at), default=None)
                if best is not None and abs(best - fired_at) <= tolerance:
                    candidates.remove(best)
                    matched += 1
                elif fired_at >= since:
                    # Pre-window jobs have no decision window to match.
                    temporal_only.append(schema_id)

            if job_index % 25000 == 0:
                self.stderr.write(f"matching: {job_index}/{len(jobs)} jobs")

        self.stderr.write(f"matching: done in {time.monotonic() - started_at:.1f}s")

        # A long run can start before the matching window and still block a due
        # time inside it. Fetch those older runs only for the schemas that still
        # have unmatched decisions, so the report never reads days of jobs.
        unmatched_schema_ids = [schema_id for schema_id, dues in unmatched.items() if dues]
        self.stderr.write(f"fetching earlier unfinished jobs for {len(unmatched_schema_ids)} schemas...")
        started_at = time.monotonic()
        for chunk_start in range(0, len(unmatched_schema_ids), EARLIER_JOBS_CHUNK_SIZE):
            earlier_jobs = ExternalDataJob.objects.filter(
                Q(finished_at__isnull=True) | Q(finished_at__gt=since),
                schema_id__in=unmatched_schema_ids[chunk_start : chunk_start + EARLIER_JOBS_CHUNK_SIZE],
                created_at__gte=since - TEMPORAL_OVERLAP_MAX_JOB_AGE,
                created_at__lt=match_start,
            ).values_list("schema_id", "created_at", "finished_at")
            for schema_uuid, created_at, finished_at in earlier_jobs:
                job_intervals.setdefault(str(schema_uuid), []).append((created_at, finished_at))
        self.stderr.write(f"fetched earlier unfinished jobs in {time.monotonic() - started_at:.1f}s")

        # The shadow scheduler decides overlap from its own queue, which holds no
        # sync jobs in shadow mode, so it would fire windows that Temporal
        # skipped because the previous run was still in progress.
        shadow_only: list[str] = []
        temporal_overlap_skip: list[str] = []
        for schema_id, dues in unmatched.items():
            for due_at in dues:
                if was_in_progress_at(due_at, job_intervals.get(schema_id, []), TEMPORAL_OVERLAP_MAX_JOB_AGE):
                    temporal_overlap_skip.append(schema_id)
                else:
                    shadow_only.append(schema_id)

        self.stdout.write(f"window since {since.isoformat()} (tolerance {tolerance})")
        self.stdout.write(f"would_fire decisions: {len(decisions)}, jobs considered: {len(jobs)}")
        self.stdout.write(f"matched: {matched}")
        self.stdout.write(f"shadow_only (shadow would fire, no job): {len(shadow_only)}")
        self.stdout.write(
            f"temporal_overlap_skip (shadow would fire, Temporal run still in progress): {len(temporal_overlap_skip)}"
        )
        self.stdout.write(f"temporal_only (schedule-fired job, no decision): {len(temporal_only)}")
        self.stdout.write(f"adhoc (manual/backfill runs, excluded): {adhoc}")
        _print_offenders(self.stdout, "shadow_only", shadow_only)
        _print_offenders(self.stdout, "temporal_overlap_skip", temporal_overlap_skip)
        _print_offenders(self.stdout, "temporal_only", temporal_only)
