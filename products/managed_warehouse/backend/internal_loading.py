from __future__ import annotations

from uuid import UUID

from django.conf import settings

import structlog
from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.temporal.common.client import async_connect

from products.data_modeling.backend.facade.api import get_materialized_table_uri
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
from products.managed_warehouse.backend.presentation import views
from products.managed_warehouse.backend.trino_target import get_ready_trino_connection_target
from products.warehouse_sources.backend.facade.api import list_imported_schema_snapshots
from products.warehouse_sources.backend.facade.contracts import ImportedSchemaSnapshot

logger = structlog.get_logger(__name__)


def load_internal_team(organization_id: str, team_id: int, generation: int) -> None:
    lifecycle = ManagedWarehouseSourceLifecycle.objects.filter(
        organization_id=organization_id, generation=generation, desired_active=True, background_loading_enabled=True
    ).first()
    if (
        lifecycle is None
        or not Team.objects.filter(
            id=team_id, organization_id=organization_id, organization__is_pending_deletion=False
        ).exists()
    ):
        return
    if not DuckgresServer.objects.filter(organization_id=organization_id).exists():
        raise RuntimeError("Internal warehouse connection has not been persisted")
    if get_ready_trino_connection_target(organization_id) is None:
        raise RuntimeError("Internal warehouse is not ready for loading")
    row = views._get_project_team_row(organization_id=organization_id, team_id=team_id)
    if row is None or not row.get("backfill_enabled"):
        raise RuntimeError("Internal warehouse team backfill is not enabled")

    schemas = list_imported_schema_snapshots(team_id)
    models = list(
        DataWarehouseSavedQuery.objects.filter(team_id=team_id, is_materialized=True, deleted=False)
        .exclude(table=None)
        .order_by("id")
    )
    model_uris = {model.id: get_materialized_table_uri(team_id, model.id) for model in models}
    async_to_sync(_start_loads)(team_id, generation, schemas, models, model_uris)
    logger.info("internal_warehouse_loading_dispatched", team_id=team_id, generation=generation)


async def _start_loads(
    team_id: int,
    generation: int,
    schemas: list[ImportedSchemaSnapshot],
    models: list[DataWarehouseSavedQuery],
    model_uris: dict[UUID, str | None],
) -> None:
    from products.managed_warehouse.backend.facade.temporal import (  # noqa: PLC0415
        DataImportsDuckLakeCopyInputs,
        DataModelingDuckLakeCopyInputs,
        DuckLakeCopyModelInput,
        DuckLakeRegisterDataImportsInputs,
        build_register_data_imports_workflow_id,
    )

    temporal = await async_connect()
    job_id = f"internal-warehouse-{team_id}-{generation}"
    for schema in schemas:
        if schema.queryable_folder:
            await _start_load(
                temporal,
                "ducklake-register.data-imports",
                DuckLakeRegisterDataImportsInputs(
                    team_id=team_id,
                    job_id=job_id,
                    schema_id=schema.schema_id,
                    prepared_queryable_folder=schema.queryable_folder,
                ),
                id=build_register_data_imports_workflow_id(team_id=team_id, schema_id=str(schema.schema_id)),
                retry_completed=True,
            )
        else:
            await _start_load(
                temporal,
                "ducklake-copy.data-imports",
                DataImportsDuckLakeCopyInputs(
                    team_id=team_id, job_id=job_id, schema_ids=[schema.schema_id], internal_bootstrap=True
                ),
                id=f"internal-warehouse-import/{team_id}/{generation}/{schema.schema_id}",
            )
    for model in models:
        if uri := model_uris[model.id]:
            await _start_load(
                temporal,
                "ducklake-copy.data-modeling",
                DataModelingDuckLakeCopyInputs(
                    team_id=team_id,
                    job_id=job_id,
                    models=[
                        DuckLakeCopyModelInput(model_label=model.id.hex, saved_query_id=str(model.id), table_uri=uri)
                    ],
                ),
                id=f"internal-warehouse-model/{team_id}/{generation}/{model.id}",
            )


async def _start_load(temporal: Client, name: str, inputs: object, *, id: str, retry_completed: bool = False) -> None:
    try:
        await temporal.start_workflow(
            name,
            inputs,
            id=id,
            task_queue=settings.DUCKLAKE_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=(
                WorkflowIDReusePolicy.ALLOW_DUPLICATE
                if retry_completed
                else WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
            ),
        )
    except WorkflowAlreadyStartedError:
        return
