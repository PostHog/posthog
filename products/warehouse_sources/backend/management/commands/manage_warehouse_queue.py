"""Ops tooling for the v3 warehouse sources load queue (delta sink).

Inspect queue state, manually fail wedged runs, and force-release stuck
coordination state (group leases, the v3 Redis pipeline lock) from a toolbox
pod. Mutating actions are dry-run by default and mirror the consumer's own
fail/reconcile semantics rather than inventing a second code path.
"""

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

import psycopg
import structlog

from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    RECOVERY_GRACE_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    _mark_job_failed_if_not_terminal,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PARTITION_PRUNING_INTERVAL,
    ActiveRunRef,
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
)

logger = structlog.get_logger(__name__)

DEFAULT_FAIL_REASON = "manually failed via manage_warehouse_queue"
MAX_RUNS_DEFAULT = 20
PRINT_LIMIT = 50


@dataclass(frozen=True)
class Scope:
    """Resolved targeting: which slice of the queue an action applies to."""

    team_id: int | None = None
    schema_ids: list[str] | None = None
    source_type: str | None = None  # set only for source-type-only targeting (resolved queue-first)
    run_uuid: str | None = None


@dataclass(frozen=True)
class FailTarget:
    """A run (or queue-less Running job) selected for fail-run."""

    run_uuid: str | None
    job_id: str
    team_id: int
    schema_id: str | None
    source_id: str | None
    workflow_run_id: str | None
    pending_batches: int
    total_batches: int


class Command(BaseCommand):
    help = (
        "Manage the v3 warehouse sources load queue: inspect state (status), manually fail "
        "wedged runs (fail-run/cancel), or force-release stuck group leases and v3 Redis "
        "pipeline locks (release-locks). Mutating actions are dry-run unless --live-run is given."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        subparsers = parser.add_subparsers(dest="action", required=True)

        status = subparsers.add_parser("status", help="Show queue state (read-only)")
        self._add_target_args(status)
        status.add_argument(
            "--stale-grace-seconds",
            type=int,
            default=RECOVERY_GRACE_SECONDS,
            help="Age threshold for reporting stale 'executing' batches",
        )

        fail_run = subparsers.add_parser(
            "fail-run",
            aliases=["cancel"],
            help="Fail wedged runs: mark pending batches failed, mark the job Failed, release locks",
        )
        self._add_target_args(fail_run)
        fail_run.add_argument("--reason", type=str, default=DEFAULT_FAIL_REASON, help="Recorded as the job's error")
        fail_run.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        fail_run.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
        fail_run.add_argument(
            "--max-runs",
            type=int,
            default=MAX_RUNS_DEFAULT,
            help=f"Abort if more than this many runs match (default {MAX_RUNS_DEFAULT})",
        )
        fail_run.add_argument(
            "--cancel-workflow",
            action="store_true",
            help="Also request cancellation of each run's Temporal workflow",
        )

        release = subparsers.add_parser(
            "release-locks",
            help="Force-release group leases and/or v3 Redis pipeline locks left behind by dead pods",
        )
        self._add_target_args(release)
        release.add_argument("--leases-only", action="store_true", help="Only release Postgres group leases")
        release.add_argument("--redis-only", action="store_true", help="Only release v3 Redis pipeline locks")
        release.add_argument("--live-run", action="store_true", help="Apply changes (default is dry-run)")
        release.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
        release.add_argument(
            "--force",
            action="store_true",
            help="Also release live leases / locks that look owned by a Running job (may abort healthy work)",
        )

    @staticmethod
    def _add_target_args(parser: CommandParser) -> None:
        parser.add_argument("--team-id", type=int, help="Scope by team")
        parser.add_argument("--schema-id", type=str, help="Scope by schema (requires --team-id)")
        parser.add_argument("--source-id", type=str, help="Scope by source (requires --team-id)")
        parser.add_argument(
            "--source-type", type=str, help="Scope by source type, e.g. Stripe (alone or with --team-id)"
        )
        parser.add_argument("--run-uuid", type=str, help="Target one queue run directly (no other targeting flags)")

    def handle(self, *args: Any, **options: Any) -> None:
        action = options["action"]
        if action == "cancel":
            action = "fail-run"

        with psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True) as conn:
            if action == "status":
                self._handle_status(conn, options)
            elif action == "fail-run":
                self._handle_fail_run(conn, options)
            elif action == "release-locks":
                self._handle_release_locks(conn, options)

    # -- targeting --------------------------------------------------------------

    def _resolve_scope(self, options: dict[str, Any], *, allow_empty: bool) -> Scope:
        team_id = options.get("team_id")
        schema_id = options.get("schema_id")
        source_id = options.get("source_id")
        source_type = options.get("source_type")
        run_uuid = options.get("run_uuid")

        if run_uuid:
            if any([team_id, schema_id, source_id, source_type]):
                raise CommandError("--run-uuid targets one run directly; don't combine it with other targeting flags")
            return Scope(run_uuid=run_uuid)

        if (schema_id or source_id) and not team_id:
            raise CommandError("--schema-id and --source-id require --team-id")

        if team_id is None and source_type is None:
            if not allow_empty:
                raise CommandError(
                    "Provide targeting flags: --team-id (optionally with --schema-id/--source-id/--source-type), "
                    "--source-type alone, or --run-uuid"
                )
            return Scope()

        if team_id is not None:
            schema_ids = self._resolve_schema_ids(
                team_id=team_id, schema_id=schema_id, source_id=source_id, source_type=source_type
            )
            return Scope(team_id=team_id, schema_ids=schema_ids)

        return Scope(source_type=source_type)

    def _resolve_schema_ids(
        self, *, team_id: int, schema_id: str | None, source_id: str | None, source_type: str | None
    ) -> list[str] | None:
        """Resolve team-scoped targeting flags to queue schema_ids via the main DB. None = whole team."""
        if schema_id:
            if not ExternalDataSchema.objects.filter(team_id=team_id, id=schema_id).exists():
                raise CommandError(f"No schema {schema_id!r} for team {team_id}")
            return [schema_id]
        if source_id:
            ids = list(
                ExternalDataSchema.objects.filter(team_id=team_id, source_id=source_id).values_list("id", flat=True)
            )
            if not ids:
                raise CommandError(f"No schemas for source {source_id!r} in team {team_id}")
            return [str(i) for i in ids]
        if source_type:
            ids = list(
                ExternalDataSchema.objects.filter(team_id=team_id, source__source_type__iexact=source_type).values_list(
                    "id", flat=True
                )
            )
            if not ids:
                raise CommandError(f"No schemas with source type {source_type!r} in team {team_id}")
            return [str(i) for i in ids]
        return None

    def _filter_runs_by_source_type(self, runs: list[ActiveRunRef], source_type: str) -> list[ActiveRunRef]:
        """Post-filter queue runs for source-type-only targeting (queue-first, then one main-DB lookup)."""
        source_ids = {r.source_id for r in runs if r.source_id}
        if not source_ids:
            return []
        matching = {
            str(pk)
            for pk in ExternalDataSource.objects.filter(id__in=source_ids, source_type__iexact=source_type).values_list(
                "id", flat=True
            )
        }
        return [r for r in runs if r.source_id in matching]

    def _running_v3_jobs(self, scope: Scope) -> list[ExternalDataJob]:
        """Main-DB branch of "active": Running V3 jobs in scope (some may have nothing in the queue)."""
        jobs = ExternalDataJob.objects.filter(
            status=ExternalDataJob.Status.RUNNING,
            pipeline_version=ExternalDataJob.PipelineVersion.V3,
        )
        if scope.team_id is not None:
            jobs = jobs.filter(team_id=scope.team_id)
        if scope.schema_ids is not None:
            jobs = jobs.filter(schema_id__in=scope.schema_ids)
        if scope.source_type is not None:
            jobs = jobs.filter(pipeline__source_type__iexact=scope.source_type)
        return list(jobs)

    def _collect_fail_targets(self, conn: psycopg.Connection[Any], scope: Scope) -> list[FailTarget]:
        runs = BatchQueue.get_active_runs(
            conn,
            team_id=scope.team_id,
            schema_ids=scope.schema_ids,
            run_uuid=scope.run_uuid,
            only_pending=scope.run_uuid is None,
        )
        if scope.source_type:
            runs = self._filter_runs_by_source_type(runs, scope.source_type)

        targets = [
            FailTarget(
                run_uuid=r.run_uuid,
                job_id=r.job_id,
                team_id=r.team_id,
                schema_id=r.schema_id,
                source_id=r.source_id,
                workflow_run_id=r.workflow_run_id,
                pending_batches=r.pending_batches,
                total_batches=r.total_batches,
            )
            for r in runs
        ]

        if scope.run_uuid:
            if not targets:
                raise CommandError(
                    f"Run {scope.run_uuid!r} has no batches inside the queue retention window "
                    f"({PARTITION_PRUNING_INTERVAL}) - nothing to fail. If its ExternalDataJob is stuck "
                    "in Running, target it via --team-id/--schema-id instead."
                )
            return targets

        # Running jobs the queue knows nothing about (producer died before enqueueing,
        # or the job-status write never landed after the batches went terminal).
        known_job_ids = {t.job_id for t in targets}
        for job in self._running_v3_jobs(scope):
            if str(job.id) in known_job_ids:
                continue
            targets.append(
                FailTarget(
                    run_uuid=None,
                    job_id=str(job.id),
                    team_id=job.team_id,
                    schema_id=str(job.schema_id) if job.schema_id else None,
                    source_id=str(job.pipeline_id) if job.pipeline_id else None,
                    workflow_run_id=job.workflow_run_id,
                    pending_batches=0,
                    total_batches=0,
                )
            )
        return targets

    # -- fail-run ---------------------------------------------------------------

    def _handle_fail_run(self, conn: psycopg.Connection[Any], options: dict[str, Any]) -> None:
        scope = self._resolve_scope(options, allow_empty=False)
        reason: str = options["reason"]
        live_run: bool = options["live_run"]
        cancel_workflow: bool = options["cancel_workflow"]

        targets = self._collect_fail_targets(conn, scope)
        if not targets:
            self.stdout.write("No active runs match - nothing to fail.")
            return

        max_runs: int = options["max_runs"]
        if len(targets) > max_runs:
            raise CommandError(
                f"{len(targets)} runs match, above the --max-runs cap of {max_runs}. "
                "Narrow the targeting or raise --max-runs explicitly."
            )

        jobs_by_id = {str(j.id): j for j in ExternalDataJob.objects.filter(id__in=[t.job_id for t in targets])}

        # Read-only lock/lease state so the dry-run preview is honest about what release will do.
        leases_by_pair = {
            (lease.team_id, lease.schema_id): lease
            for lease in BatchQueue.get_leases(conn, schema_ids=sorted({t.schema_id for t in targets if t.schema_id}))
        }

        verb = "Would fail" if not live_run else "Failing"
        self.stdout.write(f"{verb} {len(targets)} run(s):")
        for t in targets:
            job = jobs_by_id.get(t.job_id)
            job_status = job.status if job else "<job not found>"
            queue_note = (
                f"pending_batches={t.pending_batches}/{t.total_batches}"
                if t.run_uuid
                else "no queue batches in retention window (job-only)"
            )
            self.stdout.write(
                f"  run={t.run_uuid or '-'} job={t.job_id} (status={job_status}) team={t.team_id} "
                f"schema={t.schema_id or '-'} {queue_note} workflow_run_id={t.workflow_run_id or '-'}"
            )
            if t.schema_id:
                notes = []
                if t.workflow_run_id:
                    holder = get_v3_pipeline_lock_holder(t.team_id, t.schema_id)
                    if holder is None:
                        notes.append("redis lock unheld")
                    elif holder == t.workflow_run_id:
                        notes.append("redis lock held by this run (will release)")
                    else:
                        notes.append(f"redis lock held by a different token ({holder!r}) - will not release")
                lease = leases_by_pair.get((t.team_id, t.schema_id))
                if lease is not None:
                    notes.append(
                        f"lease {'LIVE' if lease.is_live else 'expired ' + self._age(lease.expires_at) + ' ago'} (will delete)"
                    )
                if notes:
                    self.stdout.write(f"    -> {'; '.join(notes)}")

        if not live_run:
            self.stdout.write("Dry run - no changes written. Re-run with --live-run to apply.")
            return

        self._confirm(f"Fail {len(targets)} run(s)? Type 'fail' to continue: ", "fail", yes=options["yes"])

        for t in targets:
            self.stdout.write(f"run={t.run_uuid or '-'} job={t.job_id}:")
            self._fail_target(conn, t, reason=reason, cancel_workflow=cancel_workflow, job=jobs_by_id.get(t.job_id))
            logger.info(
                "manage_warehouse_queue_fail_run",
                run_uuid=t.run_uuid,
                job_id=t.job_id,
                team_id=t.team_id,
                external_data_schema_id=t.schema_id,
                reason=reason,
            )

        pairs = sorted({(t.team_id, t.schema_id) for t in targets if t.schema_id})
        released = BatchQueue.force_release_leases(conn, pairs=list(pairs))
        self.stdout.write(self.style.SUCCESS(f"Done. Released {released} group lease(s)."))

    def _fail_target(
        self,
        conn: psycopg.Connection[Any],
        target: FailTarget,
        *,
        reason: str,
        cancel_workflow: bool,
        job: ExternalDataJob | None,
    ) -> None:
        """Mirror the consumer's fail path; each step isolated so one failure doesn't abort the rest."""
        if target.run_uuid:
            try:
                failed = BatchQueue.fail_run_sync(conn, run_uuid=target.run_uuid, reason=reason)
                self.stdout.write(f"  queue: marked {failed} pending batch(es) failed")
            except Exception:
                logger.exception("manage_warehouse_queue_fail_run_queue_write_failed", run_uuid=target.run_uuid)
                self.stdout.write(self.style.ERROR("  queue: FAILED to write failed statuses (see logs)"))

        try:
            transitioned = _mark_job_failed_if_not_terminal(job_id=target.job_id, team_id=target.team_id, error=reason)
            self.stdout.write("  job: marked Failed" if transitioned else "  job: already terminal - left unchanged")
        except Exception:
            logger.exception("manage_warehouse_queue_fail_run_job_update_failed", job_id=target.job_id)
            self.stdout.write(self.style.ERROR("  job: FAILED to update status (see logs)"))

        if target.workflow_run_id and target.schema_id:
            released = release_v3_pipeline_lock(target.team_id, target.schema_id, token=target.workflow_run_id)
            if released:
                self.stdout.write("  redis lock: released")
            else:
                holder = get_v3_pipeline_lock_holder(target.team_id, target.schema_id)
                if holder is None:
                    self.stdout.write("  redis lock: not held")
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  redis lock: held by a different token ({holder!r}) - a newer run may own it; "
                            "use release-locks if it is genuinely stale"
                        )
                    )

        if cancel_workflow:
            self._cancel_workflow(job)

    def _cancel_workflow(self, job: ExternalDataJob | None) -> None:
        # Deferred: pulls in the Temporal client stack, only needed with --cancel-workflow.
        from temporalio.service import RPCError  # noqa: PLC0415

        from products.data_warehouse.backend.facade.api import cancel_external_data_workflow  # noqa: PLC0415

        if job is None or not job.workflow_id:
            self.stdout.write(self.style.WARNING("  temporal: no workflow_id on the job - skipped"))
            return
        try:
            cancel_external_data_workflow(job.workflow_id)
            self.stdout.write("  temporal: cancellation requested")
        except RPCError as e:
            self.stdout.write(self.style.WARNING(f"  temporal: cancellation failed ({e.message})"))
        except Exception:
            logger.exception("manage_warehouse_queue_temporal_cancel_failed", workflow_id=job.workflow_id)
            self.stdout.write(self.style.ERROR("  temporal: cancellation failed (see logs)"))

    # -- release-locks ----------------------------------------------------------

    def _handle_release_locks(self, conn: psycopg.Connection[Any], options: dict[str, Any]) -> None:
        if options["leases_only"] and options["redis_only"]:
            raise CommandError("--leases-only and --redis-only are mutually exclusive")
        scope = self._resolve_scope(options, allow_empty=False)
        if scope.run_uuid:
            raise CommandError("release-locks targets (team, schema) pairs; --run-uuid is not supported here")

        pairs = self._resolve_lock_pairs(conn, scope)
        if not pairs:
            self.stdout.write("No (team, schema) pairs in scope - nothing to release.")
            return

        live_run: bool = options["live_run"]
        force: bool = options["force"]
        check_leases = not options["redis_only"]
        check_redis = not options["leases_only"]

        # workflow_run_ids of Running jobs, per schema: a redis lock held by one of
        # these tokens belongs to live work and needs --force.
        running_tokens: dict[str, set[str]] = {}
        for job in self._running_v3_jobs(scope):
            if job.schema_id and job.workflow_run_id:
                running_tokens.setdefault(str(job.schema_id), set()).add(job.workflow_run_id)

        leases_to_delete: list[tuple[int, str]] = []
        skipped_live_leases = 0
        if check_leases:
            leases = BatchQueue.get_leases(conn, schema_ids=[schema_id for _, schema_id in pairs])
            for lease in leases:
                if lease.is_live and not force:
                    skipped_live_leases += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  lease team={lease.team_id} schema={lease.schema_id} is LIVE "
                            f"(expires {lease.expires_at.isoformat()}, owner {lease.owner_token}) - "
                            "skipped; a healthy pod may hold it. Use --force to release anyway."
                        )
                    )
                    continue
                liveness = "LIVE (forced)" if lease.is_live else f"expired {self._age(lease.expires_at)} ago"
                self.stdout.write(f"  lease team={lease.team_id} schema={lease.schema_id}: {liveness} - release")
                leases_to_delete.append((lease.team_id, lease.schema_id))

        redis_to_release: list[tuple[int, str, str]] = []
        skipped_live_locks = 0
        if check_redis:
            for team_id, schema_id in pairs:
                holder = get_v3_pipeline_lock_holder(team_id, schema_id)
                if holder is None:
                    continue
                if holder in running_tokens.get(schema_id, set()) and not force:
                    skipped_live_locks += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  redis lock team={team_id} schema={schema_id} is held by a Running job "
                            f"({holder!r}) - skipped. Use --force to release anyway."
                        )
                    )
                    continue
                self.stdout.write(f"  redis lock team={team_id} schema={schema_id}: held by {holder!r} - release")
                redis_to_release.append((team_id, schema_id, holder))

        if not leases_to_delete and not redis_to_release:
            self.stdout.write("Nothing releasable in scope.")
            return

        if not live_run:
            self.stdout.write("Dry run - no changes written. Re-run with --live-run to apply.")
            return

        self._confirm(
            f"Release {len(leases_to_delete)} lease(s) and {len(redis_to_release)} redis lock(s)? "
            "Type 'release' to continue: ",
            "release",
            yes=options["yes"],
        )

        released_leases = BatchQueue.force_release_leases(conn, pairs=leases_to_delete)
        released_locks = 0
        for team_id, schema_id, holder in redis_to_release:
            # Token-compared delete: if a new run grabbed the lock since we read the
            # holder, the release is a no-op rather than breaking the new run.
            if release_v3_pipeline_lock(team_id, schema_id, token=holder):
                released_locks += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f"  redis lock team={team_id} schema={schema_id}: holder changed - skipped")
                )
        logger.info(
            "manage_warehouse_queue_release_locks",
            released_leases=released_leases,
            released_locks=released_locks,
            team_id=scope.team_id,
            source_type=scope.source_type,
        )
        self.stdout.write(
            self.style.SUCCESS(f"Released {released_leases} group lease(s) and {released_locks} redis lock(s).")
        )

    def _resolve_lock_pairs(self, conn: psycopg.Connection[Any], scope: Scope) -> list[tuple[int, str]]:
        """(team_id, schema_id) pairs to check for stuck coordination state."""
        if scope.team_id is not None:
            schema_ids = scope.schema_ids
            if schema_ids is None:
                schema_ids = [
                    str(i)
                    for i in ExternalDataSchema.objects.filter(team_id=scope.team_id, deleted=False).values_list(
                        "id", flat=True
                    )
                ]
            return [(scope.team_id, schema_id) for schema_id in schema_ids]

        # source-type only: bound the sweep to pairs with actual queue presence
        # (leases or active runs). Fully idle schemas' redis locks need --team-id scoping.
        runs = self._filter_runs_by_source_type(BatchQueue.get_active_runs(conn), scope.source_type or "")
        pairs = {(r.team_id, r.schema_id) for r in runs}
        lease_schema_ids = {lease.schema_id for lease in BatchQueue.get_leases(conn)}
        if lease_schema_ids:
            matching = {
                str(schema_pk): team_pk
                for schema_pk, team_pk in ExternalDataSchema.objects.filter(
                    id__in=lease_schema_ids, source__source_type__iexact=scope.source_type or ""
                ).values_list("id", "team_id")
            }
            pairs.update((team_pk, schema_id) for schema_id, team_pk in matching.items())
        self.stdout.write(
            "Note: with --source-type alone, only schemas with queue activity (batches or leases) are "
            "checked - scope with --team-id to sweep idle schemas' redis locks."
        )
        return sorted(pairs)

    # -- status -----------------------------------------------------------------

    def _handle_status(self, conn: psycopg.Connection[Any], options: dict[str, Any]) -> None:
        scope = self._resolve_scope(options, allow_empty=True)

        runs = BatchQueue.get_active_runs(
            conn,
            team_id=scope.team_id,
            schema_ids=scope.schema_ids,
            run_uuid=scope.run_uuid,
            only_pending=scope.run_uuid is None,
        )
        if scope.source_type:
            runs = self._filter_runs_by_source_type(runs, scope.source_type)

        # For source-type-only scoping, narrow the remaining sections to the schemas
        # the filtered runs actually touch (the summary query can't join source_type).
        summary_schema_ids = scope.schema_ids
        if scope.source_type and summary_schema_ids is None:
            summary_schema_ids = sorted({r.schema_id for r in runs})

        self.stdout.write(self.style.MIGRATE_HEADING("Queue summary (within retention window)"))
        summary = BatchQueue.get_state_summary(conn, team_id=scope.team_id, schema_ids=summary_schema_ids)
        if not summary:
            self.stdout.write("  no batches in scope")
        for row in summary:
            line = f"  {row['state']}: {row['batch_count']}"
            if row["state"] == "unclaimed" and row["oldest_created_at"] is not None:
                line += f" (oldest {self._age(row['oldest_created_at'])} old)"
            self.stdout.write(line)

        self.stdout.write(self.style.MIGRATE_HEADING(f"Active runs ({len(runs)})"))
        jobs_by_id = {
            str(j.id): j for j in ExternalDataJob.objects.filter(id__in=[r.job_id for r in runs[:PRINT_LIMIT]])
        }
        for r in runs[:PRINT_LIMIT]:
            job = jobs_by_id.get(r.job_id)
            job_status = job.status if job else "<job not found>"
            activity = self._age(r.latest_activity_at) + " ago" if r.latest_activity_at else "-"
            self.stdout.write(
                f"  run={r.run_uuid} job={r.job_id} (status={job_status}) team={r.team_id} schema={r.schema_id} "
                f"pending={r.pending_batches}/{r.total_batches} last_activity={activity} "
                f"workflow_run_id={r.workflow_run_id or '-'}"
            )
        if len(runs) > PRINT_LIMIT:
            self.stdout.write(f"  ... and {len(runs) - PRINT_LIMIT} more")

        known_job_ids = {r.job_id for r in runs}
        orphan_jobs = [j for j in self._running_v3_jobs(scope) if str(j.id) not in known_job_ids]
        if orphan_jobs:
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"Running V3 jobs with nothing pending in the queue ({len(orphan_jobs)}) - fail-run candidates"
                )
            )
            for job in orphan_jobs[:PRINT_LIMIT]:
                self.stdout.write(
                    f"  job={job.id} team={job.team_id} schema={job.schema_id or '-'} "
                    f"workflow_run_id={job.workflow_run_id or '-'}"
                )

        self.stdout.write(self.style.MIGRATE_HEADING("Group leases"))
        leases = BatchQueue.get_leases(conn, team_id=scope.team_id, schema_ids=summary_schema_ids)
        if not leases:
            self.stdout.write("  none in scope")
        for lease in leases[:PRINT_LIMIT]:
            liveness = "LIVE" if lease.is_live else f"EXPIRED {self._age(lease.expires_at)} ago"
            self.stdout.write(
                f"  team={lease.team_id} schema={lease.schema_id} owner={lease.owner_token} {liveness} "
                f"(expires {lease.expires_at.isoformat()})"
            )

        self.stdout.write(self.style.MIGRATE_HEADING("Redis pipeline locks"))
        workflow_tokens: dict[tuple[int, str], set[str]] = {}
        for r in runs:
            if r.workflow_run_id:
                workflow_tokens.setdefault((r.team_id, r.schema_id), set()).add(r.workflow_run_id)
        for job in orphan_jobs:
            if job.schema_id and job.workflow_run_id:
                workflow_tokens.setdefault((job.team_id, str(job.schema_id)), set()).add(job.workflow_run_id)
        lock_pairs = sorted(
            {(r.team_id, r.schema_id) for r in runs}
            | {(lease.team_id, lease.schema_id) for lease in leases}
            | {(job.team_id, str(job.schema_id)) for job in orphan_jobs if job.schema_id}
        )[:PRINT_LIMIT]
        held_any = False
        for team_id, schema_id in lock_pairs:
            holder = get_v3_pipeline_lock_holder(team_id, schema_id)
            if holder is None:
                continue
            held_any = True
            known = holder in workflow_tokens.get((team_id, schema_id), set())
            note = "" if known else " - token matches no known active workflow_run_id (stale-lock smell)"
            self.stdout.write(f"  team={team_id} schema={schema_id} holder={holder!r}{note}")
        if not held_any:
            self.stdout.write("  none held for in-scope pairs")

        grace: int = options["stale_grace_seconds"]
        stale = BatchQueue.get_stale_executing_sync(
            conn, grace_seconds=grace, team_id=scope.team_id, schema_ids=summary_schema_ids
        )
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Stale executing batches (>{grace}s, no live lease): {len(stale)}")
        )
        for batch in stale[:PRINT_LIMIT]:
            self.stdout.write(
                f"  batch={batch.id} run={batch.run_uuid} team={batch.team_id} schema={batch.schema_id} "
                f"batch_index={batch.batch_index}"
            )

    # -- shared -----------------------------------------------------------------

    def _confirm(self, prompt: str, keyword: str, *, yes: bool) -> None:
        if yes:
            return
        if not sys.stdin.isatty():
            raise CommandError("Refusing to apply changes non-interactively without --yes")
        if input(prompt).strip() != keyword:
            raise CommandError("Aborted.")

    @staticmethod
    def _age(moment: datetime) -> str:
        seconds = abs((datetime.now(UTC) - moment).total_seconds())
        if seconds < 120:
            return f"{int(seconds)}s"
        if seconds < 2 * 3600:
            return f"{int(seconds // 60)}m"
        return f"{seconds / 3600:.1f}h"
