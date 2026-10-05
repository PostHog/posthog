"""The work `ExternalDataJobWorkflow` still does after a V3 extraction, done here for a queue run.

The workflow starts these as child workflows and an activity. A queue run starts the same
workflows through a Temporal client, with the same ids, inputs and conditions. A start that fails
is logged and does not fail the run: the extraction already finished, and a retry would extract
the table again.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import dataclasses
from collections.abc import Awaitable, Callable

from django.conf import settings

from structlog.types import FilteringBoundLogger
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.utils import CDPProducerWorkflowInputs

from products.data_warehouse.backend.facade.api import create_warehouse_templates_for_source
from products.warehouse_sources.backend.queue_runs.payloads import SyncExtractPayload
from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.post_import_job import (
    PostImportWorkflow,
    PostImportWorkflowInputs,
    build_post_import_workflow_id,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityOutputs,
)

TemporalClientFactory = Callable[[], Awaitable[Client]]


class TemporalStarter:
    """Connects to Temporal once, on first use, and shares the client between runs."""

    def __init__(self, connect: TemporalClientFactory) -> None:
        self._connect = connect
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def client(self) -> Client:
        async with self._lock:
            if self._client is None:
                self._client = await self._connect()
            return self._client


# A Temporal outage must not hold the run's queue lease for long after the extraction finished.
START_TIMEOUT_SECONDS = 60.0


async def _start(name: str, start: Callable[[], Awaitable[object]], logger: FilteringBoundLogger) -> None:
    try:
        async with asyncio.timeout(START_TIMEOUT_SECONDS):
            await start()
    except WorkflowAlreadyStartedError:
        await logger.ainfo("queue_run_workflow_already_started", workflow=name)
    except Exception as e:
        await logger.aexception("queue_run_workflow_start_failed", workflow=name)
        capture_exception(e)


async def start_post_extraction_work(
    starter: TemporalStarter,
    *,
    payload: SyncExtractPayload,
    plan: CreateExternalDataJobModelActivityOutputs,
    result: PipelineResult,
    logger: FilteringBoundLogger,
) -> None:
    """The CDP producer, the person-property sync and the source templates, as the workflow runs them."""
    job_id = plan.job_id

    if result.get("should_trigger_cdp_producer", False):

        async def start_cdp_producer() -> object:
            client = await starter.client()
            return await client.start_workflow(
                "dwh-cdp-producer-job",
                dataclasses.asdict(
                    CDPProducerWorkflowInputs(team_id=payload.team_id, schema_id=str(payload.schema_id), job_id=job_id)
                ),
                id=f"dwh-cdp-producer-job-{job_id}",
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=str(settings.DATA_WAREHOUSE_CDP_PRODUCER_TASK_QUEUE),
                retry_policy=RetryPolicy(maximum_attempts=3, non_retryable_error_types=["NondeterminismError"]),
            )

        await _start("dwh-cdp-producer-job", start_cdp_producer, logger)

    if result.get("skip_post_import_activities", False):
        await logger.ainfo("Skipping post-import activities for externally managed schema")
        return

    if plan.source_type and plan.schema_name and plan.person_property_sync_enabled:

        async def start_person_property_sync() -> object:
            client = await starter.client()
            return await client.start_workflow(
                "sync-warehouse-person-properties",
                PersonPropertySyncActivityInputs(
                    team_id=payload.team_id,
                    schema_id=payload.schema_id,
                    source_id=payload.source_id,
                    job_id=job_id,
                    source_type=plan.source_type,
                    schema_name=plan.schema_name,
                    last_synced_at=plan.last_synced_at,
                ),
                id=f"sync-warehouse-person-properties-{job_id}",
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                task_queue=settings.DATA_WAREHOUSE_METADATA_TASK_QUEUE,
                execution_timeout=dt.timedelta(hours=6),
            )

        await _start("sync-warehouse-person-properties", start_person_property_sync, logger)

    if plan.source_templates_needed:
        try:
            await database_sync_to_async_pool(create_warehouse_templates_for_source)(
                team_id=payload.team_id, run_id=job_id
            )
        except Exception as e:
            await logger.aexception("queue_run_source_templates_failed")
            capture_exception(e)


async def start_post_import(
    starter: TemporalStarter, *, payload: SyncExtractPayload, job_id: str, logger: FilteringBoundLogger
) -> None:
    """Start `data-import-post-import` for a run that the handler completed itself.

    The loader starts it for a run with batches. A run with no batch never reaches the loader.
    """

    async def start_workflow() -> object:
        client = await starter.client()
        return await client.start_workflow(
            PostImportWorkflow.run,
            PostImportWorkflowInputs(
                team_id=payload.team_id,
                job_id=job_id,
                schema_id=str(payload.schema_id),
                source_id=str(payload.source_id),
            ),
            id=build_post_import_workflow_id(job_id),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
        )

    await _start("data-import-post-import", start_workflow, logger)
