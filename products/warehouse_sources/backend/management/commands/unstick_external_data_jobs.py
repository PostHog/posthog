"""Unstick external data jobs whose Temporal workflows are wedged or gone.

A job row stays in Running forever when its workflow can no longer make
progress but also can't run its cleanup path — e.g. the workflow task fails
repeatedly (nondeterminism after a non-versioned workflow code change), or the
workflow was terminated (termination skips the finally block that records the
final status). While the workflow itself is still "Running", the schema's
schedule skips every future sync (ScheduleOverlapPolicy.SKIP) and the cancel
button no-ops, because cancellation also needs a successful workflow task.

This sweeps Running jobs created before a cutoff, terminates workflows with a
stuck workflow task, fails leftover v3 queue batches, releases the v3 Redis
pipeline lock, marks the job (and schema, when this is its latest job) Failed,
and optionally triggers a fresh sync. Dry-run by default.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q

import psycopg
import structlog
from asgiref.sync import async_to_sync
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHandle
from temporalio.service import RPCError, RPCStatusCode

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.facade.api import (
    is_any_external_data_schema_paused,
    trigger_external_data_workflow,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
)
from products.warehouse_sources.backend.temporal.data_imports.row_tracking import finish_row_tracking

logger = structlog.get_logger(__name__)

DEFAULT_REASON = "Sync got stuck and was reset by PostHog"
MAX_JOBS_DEFAULT = 50
# A pending workflow task at this attempt count or higher means the workflow
# can't complete any workflow task (e.g. nondeterminism) and will never recover.
WEDGED_MIN_WFT_ATTEMPT = 3
TERMINATE_REASON = "Wedged workflow terminated by unstick_external_data_jobs"


ClassificationKind = Literal["wedged", "terminal", "gone", "healthy", "ambiguous"]


@dataclass(frozen=True)
class Classification:
    kind: ClassificationKind
    detail: str


class Command(BaseCommand):
    help = (
        "Fix external data jobs stuck in Running because their Temporal workflow is wedged "
        "(workflow task failing repeatedly) or already terminated without running cleanup. "
        "Terminates wedged workflows, fails leftover v3 batches, releases v3 locks, marks the "
        "job/schema Failed, and can retrigger the sync. Dry-run unless --live-run is given."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--created-before",
            type=str,
            required=True,
            help="Only consider Running jobs created before this ISO-8601 timestamp (e.g. 2026-07-02T00:00:00Z)",
        )
        parser.add_argument("--team-id", type=int, help="Scope by team")
        parser.add_argument("--source-type", type=str, help="Scope by source type, e.g. Stripe")
        parser.add_argument(
            "--max-jobs",
            type=int,
            default=MAX_JOBS_DEFAULT,
            help=f"Abort if more than this many jobs match (default {MAX_JOBS_DEFAULT})",
        )
        parser.add_argument("--reason", type=str, default=DEFAULT_REASON, help="Recorded as the job's error")
        parser.add_argument(
            "--terminate-healthy",
            action="store_true",
            help=(
                "Also terminate matching workflows that look healthy (no stuck workflow task). "
                "Use when every pre-cutoff run is known-broken but hasn't produced a workflow task yet."
            ),
        )
        parser.add_argument(
            "--trigger-sync",
            action="store_true",
            help="Trigger a fresh sync for each fixed schema (skipped for paused/deleted/should_sync=False schemas)",
        )
        parser.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation")

    def handle(self, *args: Any, **options: Any) -> None:
        cutoff = self._parse_cutoff(options["created_before"])
        live_run: bool = options["live_run"]
        reason: str = options["reason"]
        terminate_healthy: bool = options["terminate_healthy"]
        trigger_sync: bool = options["trigger_sync"]

        jobs = ExternalDataJob.objects.filter(status=ExternalDataJob.Status.RUNNING, created_at__lt=cutoff).order_by(
            "created_at"
        )
        if options.get("team_id") is not None:
            jobs = jobs.filter(team_id=options["team_id"])
        if options.get("source_type"):
            jobs = jobs.filter(pipeline__source_type__iexact=options["source_type"])
        jobs_list = list(jobs)

        if not jobs_list:
            self.stdout.write("No Running jobs match - nothing to do.")
            return

        max_jobs: int = options["max_jobs"]
        if len(jobs_list) > max_jobs:
            raise CommandError(
                f"{len(jobs_list)} jobs match, above the --max-jobs cap of {max_jobs}. "
                "Narrow the targeting or raise --max-jobs explicitly."
            )

        temporal = sync_connect()
        classified: list[tuple[ExternalDataJob, Classification]] = []
        verb = "Would fix" if not live_run else "Fixing"
        self.stdout.write(f"{len(jobs_list)} Running job(s) created before {cutoff.isoformat()}:")
        for job in jobs_list:
            classification = self._classify(temporal, job)
            classified.append((job, classification))
            self.stdout.write(
                f"  job={job.id} team={job.team_id} schema={job.schema_id or '-'} "
                f"pipeline={job.pipeline_version or '-'} created={job.created_at.isoformat()} "
                f"-> {classification.kind} ({classification.detail})"
            )

        actionable = [
            (job, c)
            for job, c in classified
            if c.kind in ("wedged", "terminal", "gone") or (c.kind == "healthy" and terminate_healthy)
        ]
        skipped = len(classified) - len(actionable)
        self.stdout.write(f"{verb} {len(actionable)} job(s); skipping {skipped} (healthy/ambiguous).")

        if not live_run:
            self.stdout.write("Dry run - no changes written. Re-run with --live-run to apply.")
            return
        if not actionable:
            return

        self._confirm(f"Fix {len(actionable)} job(s)? Type 'unstick' to continue: ", "unstick", yes=options["yes"])

        triggered_schemas: set[str] = set()
        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            failed_jobs = 0
            for job, classification in actionable:
                self.stdout.write(f"job={job.id}:")
                # One broken job must not abort the rest of the sweep.
                try:
                    is_latest = bool(job.schema_id) and self._is_latest_job_for_schema(job)
                    self._fix_job(conn, temporal, job, classification, reason=reason, is_latest=is_latest)
                    if trigger_sync:
                        self._maybe_trigger_sync(job, triggered_schemas, is_latest=is_latest)
                except Exception:
                    failed_jobs += 1
                    logger.exception("unstick_external_data_jobs_job_failed", job_id=str(job.id))
                    self.stdout.write(self.style.ERROR("  FAILED to fix this job (see logs) - continuing"))
                    continue
                logger.info(
                    "unstick_external_data_jobs_fixed",
                    job_id=str(job.id),
                    team_id=job.team_id,
                    external_data_schema_id=str(job.schema_id) if job.schema_id else None,
                    classification=classification.kind,
                )

        summary = f"Done. Fixed {len(actionable) - failed_jobs} job(s)."
        if failed_jobs:
            summary += f" {failed_jobs} job(s) FAILED to fix (see logs)."
        self.stdout.write(self.style.SUCCESS(summary))

    # -- classification -----------------------------------------------------------

    def _classify(self, temporal: Client, job: ExternalDataJob) -> Classification:
        if not job.workflow_id or not job.workflow_run_id:
            return Classification("gone", "no workflow id on the job")

        handle = temporal.get_workflow_handle(job.workflow_id, run_id=job.workflow_run_id)
        try:
            desc = async_to_sync(handle.describe)()
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                return Classification("gone", "workflow not found (outside retention?)")
            return Classification("ambiguous", f"describe failed: {e.message}")
        except Exception as e:
            return Classification("ambiguous", f"describe failed: {e}")

        if desc.status is None:
            return Classification("ambiguous", "describe returned no status")

        if desc.status != WorkflowExecutionStatus.RUNNING:
            return Classification("terminal", f"workflow already {desc.status.name}")

        raw = desc.raw_description
        if raw.HasField("pending_workflow_task") and raw.pending_workflow_task.attempt >= WEDGED_MIN_WFT_ATTEMPT:
            return Classification("wedged", f"workflow task stuck at attempt {raw.pending_workflow_task.attempt}")

        return Classification("healthy", "running with no stuck workflow task")

    # -- fixing ---------------------------------------------------------------

    def _fix_job(
        self,
        conn: psycopg.Connection[Any],
        temporal: Client,
        job: ExternalDataJob,
        classification: Classification,
        *,
        reason: str,
        is_latest: bool,
    ) -> None:
        """External calls are individually isolated so the job row still gets fixed when
        one of them fails; handle() isolates whole jobs from each other."""
        if classification.kind in ("wedged", "healthy"):
            self._terminate_workflow(temporal, job)

        is_v3 = job.pipeline_version == ExternalDataJob.PipelineVersion.V3
        if is_v3:
            # Leftover claimable batches must go terminal before the job is failed:
            # loaded afterwards they could stale-overwrite newer data or flip the
            # job status via the final-batch sentinel.
            try:
                failed_batches = BatchQueue.fail_batches_for_job_sync(conn, job_id=str(job.id), reason=reason)
                self.stdout.write(f"  queue: marked {failed_batches} batch(es) failed")
            except Exception:
                logger.exception("unstick_external_data_jobs_queue_write_failed", job_id=str(job.id))
                self.stdout.write(self.style.ERROR("  queue: FAILED to write failed statuses (see logs)"))

        now = datetime.now(UTC)
        updated = ExternalDataJob.objects.filter(id=job.id, status=ExternalDataJob.Status.RUNNING).update(
            status=ExternalDataJob.Status.FAILED, latest_error=reason, finished_at=now, updated_at=now
        )
        self.stdout.write("  job: marked Failed" if updated else "  job: no longer Running - left unchanged")

        if is_v3 and job.schema_id and job.workflow_run_id:
            # Token-compared release: a lock acquired by a newer run is untouched.
            released = release_v3_pipeline_lock(job.team_id, str(job.schema_id), token=job.workflow_run_id)
            if released:
                self.stdout.write("  redis lock: released")
            elif get_v3_pipeline_lock_holder(job.team_id, str(job.schema_id)) is not None:
                self.stdout.write("  redis lock: held by a different token - left in place")

        if is_latest and job.schema_id:
            schema_updated = ExternalDataSchema.objects.filter(
                id=job.schema_id, team_id=job.team_id, status=ExternalDataSchema.Status.RUNNING
            ).update(status=ExternalDataSchema.Status.FAILED, latest_error=reason, updated_at=now)
            if schema_updated:
                self.stdout.write("  schema: marked Failed")
            try:
                async_to_sync(finish_row_tracking)(job.team_id, str(job.schema_id))
            except Exception:
                logger.exception("unstick_external_data_jobs_row_tracking_failed", job_id=str(job.id))

    def _terminate_workflow(self, temporal: Client, job: ExternalDataJob) -> None:
        if not job.workflow_id or not job.workflow_run_id:
            self.stdout.write(self.style.WARNING("  temporal: no workflow id on the job - terminate skipped"))
            return
        handle: WorkflowHandle[Any, Any] = temporal.get_workflow_handle(job.workflow_id, run_id=job.workflow_run_id)
        try:
            async_to_sync(handle.terminate)(reason=TERMINATE_REASON)
            self.stdout.write("  temporal: workflow terminated")
        except RPCError as e:
            self.stdout.write(self.style.WARNING(f"  temporal: terminate failed ({e.message})"))
        except Exception:
            logger.exception("unstick_external_data_jobs_terminate_failed", workflow_id=job.workflow_id)
            self.stdout.write(self.style.ERROR("  temporal: terminate failed (see logs)"))

    def _maybe_trigger_sync(self, job: ExternalDataJob, triggered_schemas: set[str], *, is_latest: bool) -> None:
        if not job.schema_id or str(job.schema_id) in triggered_schemas:
            return
        if not is_latest:
            self.stdout.write("  sync: newer job exists for schema - not retriggering")
            return

        schema = ExternalDataSchema.objects.filter(id=job.schema_id, team_id=job.team_id).first()
        if schema is None or schema.deleted or not schema.should_sync:
            self.stdout.write("  sync: schema deleted or sync disabled - not retriggering")
            return
        # Same guard the reload/resync endpoints apply before triggering a sync: a
        # Paused schema on the team means syncing was deliberately stopped, so a
        # bulk sweep shouldn't restart it.
        if is_any_external_data_schema_paused(job.team_id):
            self.stdout.write("  sync: team has a paused schema - not retriggering")
            return

        try:
            trigger_external_data_workflow(schema)
            triggered_schemas.add(str(job.schema_id))
            self.stdout.write("  sync: triggered")
        except RPCError as e:
            self.stdout.write(self.style.WARNING(f"  sync: trigger failed ({e.message})"))
        except Exception:
            logger.exception("unstick_external_data_jobs_trigger_failed", schema_id=str(job.schema_id))
            self.stdout.write(self.style.ERROR("  sync: trigger failed (see logs)"))

    # -- shared -----------------------------------------------------------------

    def _is_latest_job_for_schema(self, job: ExternalDataJob) -> bool:
        # id is the created_at tiebreak (UUIDT ids are time-ordered) so two jobs
        # sharing a timestamp can't both count as latest.
        return (
            not ExternalDataJob.objects.filter(schema_id=job.schema_id, team_id=job.team_id)
            .filter(Q(created_at__gt=job.created_at) | Q(created_at=job.created_at, id__gt=job.id))
            .exclude(id=job.id)
            .exists()
        )

    @staticmethod
    def _parse_cutoff(raw: str) -> datetime:
        try:
            cutoff = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            raise CommandError(f"--created-before is not a valid ISO-8601 timestamp: {raw!r}")
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        return cutoff

    def _confirm(self, prompt: str, keyword: str, *, yes: bool) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise CommandError("Refusing to apply changes non-interactively without --yes")
        if input(prompt).strip() != keyword:
            raise CommandError("Aborted.")
