"""Teardown of in-flight sync work when a schema stops syncing.

Setting ``should_sync=False`` (or soft-deleting a schema) only stops the scheduler
from starting new runs. Without this teardown, an in-flight run keeps its Temporal
workflow alive, its ExternalDataJob in Running, and its already-enqueued v3 queue
batches claimable. A run that is still trickling batches falls through both
reconcile sweeps (it has no failed batch and it has loader progress), so its queue
depth is consumed until the run would have finished on its own.

``teardown_run`` is the per-run core shared with the ``manage_warehouse_queue``
``fail-run`` ops command; ``teardown_schema_syncs`` is the schema-level
orchestration the ``cleanup_disabled_external_data_schema`` Celery task runs.
Every step is idempotent: pending batches already failed are not re-failed, a
terminal job is left unchanged, and lock releases are token-compared.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
)

logger = structlog.get_logger(__name__)

SYNC_TEARDOWN_ERRORS = Counter(
    "dwh_sync_teardown_errors",
    "Errors hit while tearing down in-flight sync work after a schema stopped syncing",
)


@dataclass(frozen=True, kw_only=True)
class RunTeardownOutcome:
    """Per-step result of failing one run, so callers can report or retry precisely.

    ``batches_failed`` is None when there was no queue run to touch or the queue
    write raised (``queue_write_failed`` distinguishes the two). ``job_transitioned``
    is None when the job-status write raised, False when the job was already
    terminal. ``lock_released`` is None when there was no token to compare against;
    ``lock_holder`` carries the current holder when the release was refused.
    """

    batches_failed: int | None
    queue_write_failed: bool
    job_transitioned: bool | None
    lock_released: bool | None
    lock_holder: str | None


@dataclass(frozen=True, kw_only=True)
class SchemaTeardownSummary:
    runs_failed: int
    batches_failed: int
    jobs_finalized: int
    leases_released: int
    workflows_cancelled: int
    errors: int


@frozen(frozen=False)
class _TeardownCounters:
    """Mutable tally each cleanup phase adds to; frozen into a summary at the end."""

    runs_failed: int = 0
    batches_failed: int = 0
    jobs_finalized: int = 0
    leases_released: int = 0
    workflows_cancelled: int = 0
    errors: int = 0


def teardown_run(
    conn: psycopg.Connection[Any] | None,
    *,
    run_uuid: str | None,
    job_id: str,
    team_id: int,
    schema_id: str | None,
    workflow_run_id: str | None,
    reason: str,
    queue: type[BatchQueue] = BatchQueue,
) -> RunTeardownOutcome:
    """Fail one run's pending batches, mark its job Failed, release its v3 Redis lock.

    Each step is isolated so one failure doesn't abort the rest; the outcome
    records what actually happened. Failing the batches before anything can
    also serve as the reconcile backstop: once a run has a failed batch, the
    consumers' ``get_failed_runs`` sweep will finish the cleanup even if the
    remaining steps here never succeed.
    """
    # Deferred: consumer.py pulls in the batch-consumer engine, which callers on the
    # django.setup() path (models, Celery autodiscovery) must not pay for.
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (  # noqa: PLC0415
        mark_job_failed_if_not_terminal,
    )

    batches_failed: int | None = None
    queue_write_failed = False
    if run_uuid and conn is not None:
        try:
            batches_failed = queue.fail_run_sync(conn, run_uuid=run_uuid, reason=reason)
        except Exception:
            logger.exception("sync_teardown_queue_write_failed", run_uuid=run_uuid, job_id=job_id)
            queue_write_failed = True

    job_transitioned: bool | None = None
    try:
        job_transitioned = mark_job_failed_if_not_terminal(job_id=job_id, team_id=team_id, error=reason)
    except Exception:
        logger.exception("sync_teardown_job_update_failed", job_id=job_id)

    lock_released: bool | None = None
    lock_holder: str | None = None
    if workflow_run_id and schema_id:
        lock_released = release_v3_pipeline_lock(team_id, schema_id, token=workflow_run_id)
        if not lock_released:
            lock_holder = get_v3_pipeline_lock_holder(team_id, schema_id)

    return RunTeardownOutcome(
        batches_failed=batches_failed,
        queue_write_failed=queue_write_failed,
        job_transitioned=job_transitioned,
        lock_released=lock_released,
        lock_holder=lock_holder,
    )


def _connect_queue(*, team_id: int, schema_id: str, counters: _TeardownCounters) -> psycopg.Connection[Any] | None:
    try:
        return psycopg.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    except Exception:
        # Queue-side cleanup will happen on the retry; the caller still finalizes jobs
        # and cancels workflows so the run stops producing work in the meantime.
        logger.exception("sync_teardown_queue_connect_failed", team_id=team_id, external_data_schema_id=schema_id)
        counters.errors += 1
        return None


def _fail_active_runs(
    conn: psycopg.Connection[Any], *, team_id: int, schema_id: str, reason: str, counters: _TeardownCounters
) -> set[str]:
    """Tear down every run the queue still tracks; returns the job ids handled here."""
    handled_job_ids: set[str] = set()
    try:
        active_runs = BatchQueue.get_active_runs(conn, team_id=team_id, schema_ids=[schema_id])
    except Exception:
        logger.exception("sync_teardown_queue_read_failed", team_id=team_id, external_data_schema_id=schema_id)
        counters.errors += 1
        return handled_job_ids

    for run in active_runs:
        outcome = teardown_run(
            conn,
            run_uuid=run.run_uuid,
            job_id=run.job_id,
            team_id=run.team_id,
            schema_id=run.schema_id,
            workflow_run_id=run.workflow_run_id,
            reason=reason,
        )
        handled_job_ids.add(run.job_id)
        counters.runs_failed += 1
        counters.batches_failed += outcome.batches_failed or 0
        if outcome.queue_write_failed or outcome.job_transitioned is None:
            counters.errors += 1
        if outcome.job_transitioned:
            counters.jobs_finalized += 1
    return handled_job_ids


def _finalize_unqueued_v3_jobs(
    conn: psycopg.Connection[Any] | None,
    running_jobs: list[ExternalDataJob],
    handled_job_ids: set[str],
    *,
    team_id: int,
    schema_id: str,
    reason: str,
    counters: _TeardownCounters,
) -> None:
    """Finalize running v3 jobs the queue knows nothing about.

    Nothing was enqueued yet, or the queue rows aged out of retention, so these
    still need the Failed marker and lock release.
    """
    for job in running_jobs:
        if str(job.id) in handled_job_ids or job.pipeline_version != ExternalDataJob.PipelineVersion.V3:
            continue
        outcome = teardown_run(
            conn,
            run_uuid=None,
            job_id=str(job.id),
            team_id=team_id,
            schema_id=schema_id,
            workflow_run_id=job.workflow_run_id,
            reason=reason,
        )
        if outcome.job_transitioned is None:
            counters.errors += 1
        if outcome.job_transitioned:
            counters.jobs_finalized += 1


def _release_expired_leases(
    conn: psycopg.Connection[Any], *, team_id: int, schema_id: str, counters: _TeardownCounters
) -> None:
    """Drop only expired leases: a live lease belongs to a consumer pod that will
    finish its claimed batches and let the lease lapse once nothing is pending.
    """
    try:
        expired_pairs = [
            (lease.team_id, lease.schema_id)
            for lease in BatchQueue.get_leases(conn, team_id=team_id, schema_ids=[schema_id])
            if not lease.is_live
        ]
        if expired_pairs:
            counters.leases_released += BatchQueue.force_release_leases(conn, pairs=expired_pairs)
    except Exception:
        logger.exception("sync_teardown_lease_release_failed", team_id=team_id, external_data_schema_id=schema_id)
        counters.errors += 1


def _cancel_workflows(
    running_jobs: list[ExternalDataJob],
    *,
    team_id: int,
    reason: str,
    exclude_workflow_id: str | None,
    counters: _TeardownCounters,
) -> None:
    """Cancel each running job's Temporal workflow, skipping the excluded caller."""
    # Deferred: the Temporal client stack stays off the import path of everything
    # that imports this module for the dataclasses alone.
    import temporalio.service  # noqa: PLC0415

    from products.data_warehouse.backend.facade.api import cancel_external_data_workflow  # noqa: PLC0415
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (  # noqa: PLC0415
        mark_job_failed_if_not_terminal,
    )

    for job in running_jobs:
        if not job.workflow_id or job.workflow_id == exclude_workflow_id:
            continue
        try:
            cancel_external_data_workflow(job.workflow_id)
            counters.workflows_cancelled += 1
        except temporalio.service.RPCError as e:
            if e.status != temporalio.service.RPCStatusCode.NOT_FOUND:
                logger.exception("sync_teardown_workflow_cancel_failed", workflow_id=job.workflow_id)
                counters.errors += 1
                continue
            # Already finished or terminated. v1/v2 jobs rely on the workflow to write
            # their terminal status, so unstick them here (the v3 marker was already written).
            if job.pipeline_version != ExternalDataJob.PipelineVersion.V3:
                try:
                    mark_job_failed_if_not_terminal(job_id=str(job.id), team_id=team_id, error=reason)
                except Exception:
                    logger.exception("sync_teardown_job_update_failed", job_id=str(job.id))
                    counters.errors += 1
        except Exception:
            logger.exception("sync_teardown_workflow_cancel_failed", workflow_id=job.workflow_id)
            counters.errors += 1


def teardown_schema_syncs(
    *,
    team_id: int,
    schema_id: str,
    reason: str,
    exclude_workflow_id: str | None = None,
) -> SchemaTeardownSummary:
    """Stop all in-flight sync work for a schema that no longer syncs.

    Ordering mirrors the schema ``cancel`` endpoint: the Failed job marker is
    written first (terminal statuses absorb any later status write from the
    workflow), then queue batches are failed, then the Temporal workflow is asked
    to cancel. ``exclude_workflow_id`` skips cancelling the caller's own workflow
    when the disable originates from inside a run's failure handling; the batch
    and job cleanup still applies there.

    Each phase runs even after an earlier one failed, so the retry has less to
    redo. Raises when any phase reported an error, so the Celery task retries;
    every step is a no-op on rows it already processed.
    """
    counters = _TeardownCounters()
    running_jobs = list(
        ExternalDataJob.objects.filter(team_id=team_id, schema_id=schema_id, status=ExternalDataJob.Status.RUNNING)
    )

    conn = _connect_queue(team_id=team_id, schema_id=schema_id, counters=counters)
    try:
        handled_job_ids: set[str] = set()
        if conn is not None:
            handled_job_ids = _fail_active_runs(
                conn, team_id=team_id, schema_id=schema_id, reason=reason, counters=counters
            )
        _finalize_unqueued_v3_jobs(
            conn, running_jobs, handled_job_ids, team_id=team_id, schema_id=schema_id, reason=reason, counters=counters
        )
        if conn is not None:
            _release_expired_leases(conn, team_id=team_id, schema_id=schema_id, counters=counters)
    finally:
        if conn is not None:
            conn.close()

    _cancel_workflows(
        running_jobs, team_id=team_id, reason=reason, exclude_workflow_id=exclude_workflow_id, counters=counters
    )

    summary = SchemaTeardownSummary(
        runs_failed=counters.runs_failed,
        batches_failed=counters.batches_failed,
        jobs_finalized=counters.jobs_finalized,
        leases_released=counters.leases_released,
        workflows_cancelled=counters.workflows_cancelled,
        errors=counters.errors,
    )
    logger.info(
        "sync_teardown_completed",
        team_id=team_id,
        external_data_schema_id=schema_id,
        reason=reason,
        **summary.__dict__,
    )
    if counters.errors:
        SYNC_TEARDOWN_ERRORS.inc(counters.errors)
        raise RuntimeError(
            f"Sync teardown for schema {schema_id} hit {counters.errors} error(s); retry will re-run the remaining steps"
        )
    return summary
