import uuid
import dataclasses
from typing import Any

from django.db import close_old_connections

import psycopg
import structlog
from asgiref.sync import async_to_sync
from structlog.contextvars import bind_contextvars
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus

from posthog.exceptions_capture import capture_exception
from posthog.settings import WAREHOUSE_SOURCES_DATABASE_URL
from posthog.temporal.common.client import sync_connect
from posthog.temporal.common.logger import get_logger

from products.data_warehouse.backend.facade.api import update_external_job_status
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.metrics import (
    LOCK_TAKEOVER_LATEST_ERROR,
    TERMINAL_JOB_STATUSES,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    acquire_v3_pipeline_lock,
    get_v3_pipeline_lock_holder,
    release_v3_pipeline_lock,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    is_pipeline_v3_enabled,
)

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class CheckPipelineVersionActivityInputs:
    team_id: int
    source_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class CheckPipelineVersionActivityOutputs:
    is_v3: bool


@dataclasses.dataclass
class AcquireV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID


@dataclasses.dataclass(frozen=True)
class AcquireV3LockActivityOutputs:
    acquired: bool
    token: str


@dataclasses.dataclass
class ReleaseV3LockActivityInputs:
    team_id: int
    schema_id: uuid.UUID
    token: str


@activity.defn
def check_pipeline_version_activity(inputs: CheckPipelineVersionActivityInputs) -> CheckPipelineVersionActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)
    close_old_connections()

    try:
        source = ExternalDataSource.objects.get(id=inputs.source_id)
    except ExternalDataSource.DoesNotExist:
        return CheckPipelineVersionActivityOutputs(is_v3=False)

    is_v3 = is_pipeline_v3_enabled(inputs.team_id, source.source_type)
    return CheckPipelineVersionActivityOutputs(is_v3=is_v3)


@activity.defn
def acquire_v3_pipeline_lock_activity(inputs: AcquireV3LockActivityInputs) -> AcquireV3LockActivityOutputs:
    bind_contextvars(team_id=inputs.team_id)

    logger = LOGGER.bind()

    token = activity.info().workflow_run_id or ""
    if not token:
        logger.error("v3_pipeline_lock_missing_workflow_run_id", schema_id=str(inputs.schema_id))
        return AcquireV3LockActivityOutputs(acquired=False, token="")

    acquired = acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)
    if not acquired:
        acquired = _take_over_lock_if_holder_finished(inputs, token, logger)

    logger.info(
        "v3_pipeline_lock_acquire_result",
        schema_id=str(inputs.schema_id),
        acquired=acquired,
        token=token,
    )

    return AcquireV3LockActivityOutputs(acquired=acquired, token=token)


def _take_over_lock_if_holder_finished(inputs: AcquireV3LockActivityInputs, token: str, logger: Any) -> bool:
    """Decide whether to take over the Redis pipeline lock from its current holder.

    Decision matrix (fail closed on any ambiguity):
    1. Holder workflow still RUNNING per Temporal describe -> fail closed.
    2. No job row or workflow id for the holder -> fail closed.
    3. Holder workflow terminal + job terminal -> take over.
    4. Holder workflow terminal + job RUNNING -> consult queue DB:
       - no batches or all-terminal/stale -> mark job FAILED, take over.
       - non-terminal batches with recent activity -> fail closed.
    5. Describe error / queue DB error -> fail closed.
    """
    holder = get_v3_pipeline_lock_holder(inputs.team_id, str(inputs.schema_id))
    if holder is None:
        return acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)

    close_old_connections()

    # Step 1: check if the holder's Temporal workflow is still running
    workflow_status, holder_job = _describe_holder_workflow(inputs, holder, logger)
    if workflow_status is None:
        # Describe failed - fail closed (ambiguous)
        logger.warning(
            "v3_pipeline_lock_takeover_ambiguous",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="temporal_describe_failed",
        )
        return False

    if workflow_status == WorkflowExecutionStatus.RUNNING:
        return False

    # Step 2/3: workflow is terminal, check the job row
    if holder_job is None:
        logger.warning(
            "v3_pipeline_lock_takeover_ambiguous",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="no_job_row",
        )
        return False

    if holder_job.status in TERMINAL_JOB_STATUSES:
        logger.warning(
            "v3_pipeline_lock_taking_over",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="job_terminal",
            holder_job_status=holder_job.status,
        )
        return _release_and_acquire(inputs, holder, token)

    # Step 4: workflow terminal but job still RUNNING - consult queue DB
    return _take_over_stale_running_job(inputs, holder, token, holder_job, logger)


def _describe_holder_workflow(
    inputs: AcquireV3LockActivityInputs,
    holder_run_id: str,
    logger: Any,
) -> tuple[WorkflowExecutionStatus | None, ExternalDataJob | None]:
    """Describe the holder's Temporal workflow and return (status, job), or (None, None) on error."""
    try:
        holder_job = (
            ExternalDataJob.objects.filter(
                team_id=inputs.team_id,
                schema_id=inputs.schema_id,
                workflow_run_id=holder_run_id,
            )
            .order_by("-created_at")
            .only("id", "status", "workflow_id")
            .first()
        )
        if holder_job is None or not holder_job.workflow_id:
            return None, holder_job

        temporal: Client = sync_connect()
        handle = temporal.get_workflow_handle(holder_job.workflow_id, run_id=holder_run_id)
        desc = async_to_sync(handle.describe)()
        return desc.status, holder_job
    except Exception as e:
        logger.warning(
            "v3_pipeline_lock_describe_failed",
            schema_id=str(inputs.schema_id),
            holder_run_id=holder_run_id,
            error=str(e),
        )
        capture_exception(e)
        return None, None


def _take_over_stale_running_job(
    inputs: AcquireV3LockActivityInputs,
    holder: str,
    token: str,
    holder_job: ExternalDataJob,
    logger: Any,
) -> bool:
    """Consult queue DB for a RUNNING job whose workflow is terminal."""
    try:
        conn = psycopg.Connection.connect(WAREHOUSE_SOURCES_DATABASE_URL, autocommit=True)
    except Exception as e:
        logger.warning(
            "v3_pipeline_lock_takeover_ambiguous",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="queue_db_connect_failed",
            error=str(e),
        )
        capture_exception(e)
        return False

    try:
        summary = BatchQueue.get_run_activity_summary(
            conn,
            job_id=str(holder_job.id),
            workflow_run_id=holder,
        )
    except Exception as e:
        logger.warning(
            "v3_pipeline_lock_takeover_ambiguous",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="queue_db_query_failed",
            error=str(e),
        )
        capture_exception(e)
        return False
    finally:
        conn.close()

    if summary.has_non_terminal and not summary.is_stale:
        # Consumer is actively processing batches - don't steal
        logger.info(
            "v3_pipeline_lock_takeover_skipped",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            reason="active_consumer",
        )
        return False

    # No batches, all terminal, or stale - mark job FAILED and take over
    takeover_logger = structlog.get_logger(__name__).bind(team_id=inputs.team_id)
    try:
        update_external_job_status(
            job_id=str(holder_job.id),
            team_id=inputs.team_id,
            status=ExternalDataJob.Status.FAILED,
            logger=takeover_logger,
            latest_error=LOCK_TAKEOVER_LATEST_ERROR,
        )
    except Exception as e:
        logger.warning(
            "v3_pipeline_lock_takeover_job_fail_error",
            schema_id=str(inputs.schema_id),
            holder_token=holder,
            error=str(e),
        )
        capture_exception(e)
        return False

    logger.warning(
        "v3_pipeline_lock_taking_over",
        schema_id=str(inputs.schema_id),
        holder_token=holder,
        reason="stale_running_job",
        holder_job_id=str(holder_job.id),
        has_batches=summary.has_batches,
        is_stale=summary.is_stale,
    )
    return _release_and_acquire(inputs, holder, token)


def _release_and_acquire(inputs: AcquireV3LockActivityInputs, holder: str, token: str) -> bool:
    release_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), holder)
    return acquire_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), token)


@activity.defn
def release_v3_pipeline_lock_activity(inputs: ReleaseV3LockActivityInputs) -> None:
    bind_contextvars(team_id=inputs.team_id)
    release_v3_pipeline_lock(inputs.team_id, str(inputs.schema_id), inputs.token)
