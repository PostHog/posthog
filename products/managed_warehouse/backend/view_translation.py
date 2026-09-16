from __future__ import annotations

import asyncio
from uuid import UUID

from django.conf import settings
from django.utils import timezone

import structlog
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import sync_connect

from products.managed_warehouse.backend.models import ManagedWarehouseViewTranslationJob
from products.managed_warehouse.backend.trino_compiler import get_ready_trino_catalog_name
from products.managed_warehouse.backend.view_translation_status import TRINO_TARGET_NOT_READY_MESSAGE

logger = structlog.get_logger(__name__)


def start_managed_warehouse_view_translation(job_id: UUID | str, organization_id: UUID | str) -> None:
    job = ManagedWarehouseViewTranslationJob.objects.get(id=job_id, organization_id=organization_id)
    if job.status != ManagedWarehouseViewTranslationJob.Status.PENDING:
        return

    if get_ready_trino_catalog_name(str(organization_id)) is None:
        # A workflow started now reaches the same readiness guard and fails on its first activity,
        # so fail the job here instead and leave Temporal out of it.
        ManagedWarehouseViewTranslationJob.objects.filter(id=job.id, organization_id=organization_id).update(
            status=ManagedWarehouseViewTranslationJob.Status.FAILED,
            latest_error=TRINO_TARGET_NOT_READY_MESSAGE,
            finished_at=timezone.now(),
        )
        logger.warning("managed_warehouse_view_translation_trino_target_not_ready", job_id=str(job.id))
        return

    workflow_id = f"managed-warehouse-view-translation/{job.id}"
    ManagedWarehouseViewTranslationJob.objects.filter(id=job.id, organization_id=organization_id).update(
        workflow_id=workflow_id
    )

    try:
        temporal = sync_connect()
        handle = asyncio.run(
            temporal.start_workflow(
                "managed-warehouse.translate-views",
                str(job.id),
                id=workflow_id,
                task_queue=settings.DUCKLAKE_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        )
    except Exception as error:
        ManagedWarehouseViewTranslationJob.objects.filter(id=job.id, organization_id=organization_id).update(
            status=ManagedWarehouseViewTranslationJob.Status.FAILED,
            latest_error=str(error)[:4000],
            finished_at=timezone.now(),
        )
        logger.exception("failed_to_start_managed_warehouse_view_translation", job_id=str(job.id))
        capture_exception(error)
        return

    ManagedWarehouseViewTranslationJob.objects.filter(id=job.id, organization_id=organization_id).update(
        workflow_id=workflow_id,
        workflow_run_id=handle.run_id,
    )
