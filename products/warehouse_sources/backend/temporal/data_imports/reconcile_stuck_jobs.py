"""Proactive reconciler for v3 data-import jobs wedged in RUNNING.

A v3 ``ExternalDataJob`` only leaves RUNNING when its own Temporal workflow stamps a
terminal status, or when a *later* sync attempt performs an opportunistic lock takeover
(see ``acquire_v3_lock.py``). If the workflow dies and no new sync ever fires — or the
takeover bails on any ambiguity (describe error, queue-DB error) — the job sits in RUNNING
indefinitely, silently corrupting every insight built on that table and emitting no
terminal app-metrics alert.

This sweep is the backstop: it periodically finds jobs stuck in RUNNING whose owning
workflow is already terminal and force-fails them independent of a new sync. Every
fail-closed branch below simply defers the job to the next sweep instead of touching it,
so an ambiguous read is a retry rather than a wrong write.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from django.db import close_old_connections
from django.utils import timezone

import psycopg
import structlog
from asgiref.sync import async_to_sync
from prometheus_client import Counter, Gauge
from temporalio.client import Client, WorkflowExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.facade.api import update_external_job_status
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.temporal.data_imports.metrics import LOCK_TAKEOVER_LATEST_ERROR
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    release_v3_pipeline_lock,
)

logger = structlog.get_logger(__name__)

# Pre-filter: a v3 job whose row hasn't been touched for this long is a cheap candidate for
# the authoritative Temporal check below. A healthy sync keeps updated_at fresh via progress
# writes; a dead workflow stops, so its job ages past this window. False positives here cost
# only a describe call — the workflow status, not this threshold, decides whether to fail.
STUCK_RUNNING_JOB_MIN_AGE_SECONDS = 60 * 60

# Cap per sweep so a backlog of long-running jobs can't turn one sweep into a describe storm.
# Oldest-first ordering means the stalest jobs are always reconciled first.
STUCK_RUNNING_JOB_SWEEP_LIMIT = 200

STUCK_RUNNING_JOBS_RECONCILED = Counter(
    "warehouse_stuck_running_jobs_reconciled_total",
    "Stuck-RUNNING v3 data import jobs processed by the proactive reconciler, by outcome.",
    labelnames=["outcome"],
)

# Set each sweep to the number of v3 jobs still RUNNING past the staleness pre-filter — the
# signal an alert can watch so a wedged sync surfaces instead of silently going stale.
STUCK_RUNNING_JOBS_CANDIDATES = Gauge(
    "warehouse_stuck_running_jobs_candidates",
    "v3 data import jobs stuck in RUNNING past the staleness pre-filter at the last reconciler sweep.",
    multiprocess_mode="max",
)


def find_stuck_running_jobs(*, min_age_seconds: int, limit: int) -> list[ExternalDataJob]:
    """Cheap pre-filter: v3 jobs still RUNNING with no row activity for ``min_age_seconds``."""
    cutoff = timezone.now() - dt.timedelta(seconds=min_age_seconds)
    return list(
        ExternalDataJob.objects.filter(
            status=ExternalDataJob.Status.RUNNING,
            pipeline_version=ExternalDataJob.PipelineVersion.V3,
            updated_at__lt=cutoff,
        )
        .order_by("updated_at")
        .only("id", "team_id", "schema_id", "workflow_id", "workflow_run_id")[:limit]
    )


def _describe_workflow_status(temporal: Client, workflow_id: str, run_id: str) -> WorkflowExecutionStatus | None:
    """Return the workflow's status, or None if the describe failed (ambiguous — retried next sweep)."""
    try:
        handle = temporal.get_workflow_handle(workflow_id, run_id=run_id)
        desc = async_to_sync(handle.describe)()
        return desc.status
    except Exception as e:
        logger.warning("stuck_job_reconcile_describe_failed", workflow_id=workflow_id, run_id=run_id, error=str(e))
        capture_exception(e)
        return None


def _run_queue_is_reclaimable(*, job_id: str, workflow_run_id: str) -> bool | None:
    """Consult the queue DB for a terminal-workflow run.

    Returns True when the run is stale or has no live batches (safe to fail), False when a
    consumer is still actively draining it (leave it — the consumer will finish or fail it),
    or None on a connect/query error (ambiguous — retried next sweep).
    """
    try:
        conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    except Exception as e:
        logger.warning("stuck_job_reconcile_queue_connect_failed", job_id=job_id, error=str(e))
        capture_exception(e)
        return None

    try:
        summary = BatchQueue.get_run_activity_summary(conn, job_id=job_id, workflow_run_id=workflow_run_id)
    except Exception as e:
        logger.warning("stuck_job_reconcile_queue_query_failed", job_id=job_id, error=str(e))
        capture_exception(e)
        return None
    finally:
        conn.close()

    return not (summary.has_non_terminal and not summary.is_stale)


def reclaim_job_if_workflow_terminal(job: ExternalDataJob, temporal: Client) -> str:
    """Fail one stuck-RUNNING job iff its workflow is terminal and no consumer is still draining it.

    Returns an outcome label (also used as the Prometheus metric label). Mirrors the
    opportunistic takeover's decision matrix (``_take_over_lock_if_holder_finished``) minus the
    lock acquire, so the two paths reclaim on identical signals.
    """
    team_id = job.team_id
    schema_id = str(job.schema_id) if job.schema_id else None
    if not job.workflow_id or not job.workflow_run_id or schema_id is None:
        # Nothing to describe / no schema to update — leave it for the opportunistic takeover
        # rather than risk failing a live job we can't verify.
        return "unverifiable"

    status = _describe_workflow_status(temporal, job.workflow_id, job.workflow_run_id)
    if status is None:
        return "describe_error"
    if status == WorkflowExecutionStatus.RUNNING:
        return "workflow_running"

    reclaimable = _run_queue_is_reclaimable(job_id=str(job.id), workflow_run_id=job.workflow_run_id)
    if reclaimable is None:
        return "queue_error"
    if not reclaimable:
        return "active_consumer"

    bound_logger = logger.bind(team_id=team_id, external_data_schema_id=schema_id, external_data_job_id=str(job.id))
    try:
        update_external_job_status(
            job_id=str(job.id),
            team_id=team_id,
            status=ExternalDataJob.Status.FAILED,
            logger=bound_logger,
            latest_error=LOCK_TAKEOVER_LATEST_ERROR,
        )
    except Exception as e:
        logger.warning("stuck_job_reconcile_fail_error", job_id=str(job.id), error=str(e))
        capture_exception(e)
        return "fail_error"

    # Release the pipeline lock too, else it blocks the schema's next sync until its TTL expires.
    # The job is already failed, so a lingering lock is not a reclaim failure.
    try:
        release_v3_pipeline_lock(team_id, schema_id, job.workflow_run_id)
    except Exception as e:
        logger.warning("stuck_job_reconcile_release_lock_error", job_id=str(job.id), error=str(e))
        capture_exception(e)

    bound_logger.warning("stuck_running_job_reconciled", job_id=str(job.id), workflow_status=str(status))
    return "reclaimed"


def reconcile_stuck_running_jobs(
    *,
    min_age_seconds: int = STUCK_RUNNING_JOB_MIN_AGE_SECONDS,
    limit: int = STUCK_RUNNING_JOB_SWEEP_LIMIT,
) -> dict[str, int]:
    """Force-fail v3 jobs stuck in RUNNING whose owning workflow is terminal.

    The proactive backstop to the opportunistic lock takeover, which only runs when the *next*
    sync fires (and may never). Returns a count of jobs per outcome.
    """
    close_old_connections()

    jobs = find_stuck_running_jobs(min_age_seconds=min_age_seconds, limit=limit)
    STUCK_RUNNING_JOBS_CANDIDATES.set(len(jobs))
    if not jobs:
        return {}

    logger.info("stuck_job_reconcile_sweep_start", candidate_count=len(jobs))

    temporal = sync_connect()

    outcomes: dict[str, int] = defaultdict(int)
    for job in jobs:
        try:
            outcome = reclaim_job_if_workflow_terminal(job, temporal)
        except Exception as e:
            logger.exception("stuck_job_reconcile_unhandled_error", job_id=str(job.id))
            capture_exception(e)
            outcome = "error"
        STUCK_RUNNING_JOBS_RECONCILED.labels(outcome=outcome).inc()
        outcomes[outcome] += 1

    logger.info("stuck_job_reconcile_sweep_done", **outcomes)
    return dict(outcomes)
