"""Reads and actions for warehouse sources and schemas in PostHog Admin."""

from collections.abc import Sequence
from uuid import UUID

from products.warehouse_sources.backend.facade.contracts import (
    AutoDisabledSchemaFilter,
    AutoDisabledSchemaSelection,
    AutoDisabledSchemasPage,
    AutoDisabledSchemasSummary,
    RepartitionRequest,
    SchemaReenableResult,
    SchemaReenableTarget,
    StaffActionResult,
    StaffJobsPage,
    StaffSchemasPage,
    StaffSchemaSummary,
    StaffSourceSummary,
)
from products.warehouse_sources.backend.logic.auto_disabled_schemas import (
    DAYS_CHOICES,
    DEFAULT_DAYS,
    MAX_REENABLE_PER_RUN,
    REENABLE_TIME_BUDGET_SECONDS,
    AutoDisabledSchemas,
)
from products.warehouse_sources.backend.logic.schema_staff_actions import (
    PARTITION_FORMAT_CHOICES,
    PARTITION_MODE_CHOICES,
    SchemaStaffActions,
    SchemaStaffReads,
)

__all__ = [
    "DAYS_CHOICES",
    "DEFAULT_DAYS",
    "MAX_REENABLE_PER_RUN",
    "REENABLE_TIME_BUDGET_SECONDS",
    "PARTITION_FORMAT_CHOICES",
    "PARTITION_MODE_CHOICES",
    "get_schema_for_staff",
    "get_source_for_staff",
    "list_auto_disabled_schemas_for_staff",
    "list_schema_jobs_for_staff",
    "list_source_schemas_for_staff",
    "pause_schema_schedule_for_staff",
    "recreate_schema_schedule_for_staff",
    "reenable_schemas_for_staff",
    "repartition_schema_for_staff",
    "select_auto_disabled_schemas_for_staff",
    "summarize_auto_disabled_schemas_for_staff",
    "trigger_schema_sync_for_staff",
    "unpause_schema_schedule_for_staff",
]


def get_schema_for_staff(schema_id: UUID) -> StaffSchemaSummary | None:
    return SchemaStaffReads.schema(schema_id)


def list_schema_jobs_for_staff(schema_id: UUID, page_number: str | None) -> StaffJobsPage:
    return SchemaStaffReads.jobs(schema_id, page_number)


def get_source_for_staff(source_id: UUID) -> StaffSourceSummary | None:
    return SchemaStaffReads.source(source_id)


def list_source_schemas_for_staff(source_id: UUID, page_number: str | None) -> StaffSchemasPage:
    return SchemaStaffReads.source_schemas(source_id, page_number)


def repartition_schema_for_staff(schema_id: UUID, request: RepartitionRequest) -> StaffActionResult:
    return SchemaStaffActions.repartition(schema_id, request)


def trigger_schema_sync_for_staff(schema_id: UUID, *, billable: bool, reset_pipeline: bool) -> StaffActionResult:
    return SchemaStaffActions.trigger_sync(schema_id, billable=billable, reset_pipeline=reset_pipeline)


def pause_schema_schedule_for_staff(schema_id: UUID) -> StaffActionResult:
    return SchemaStaffActions.pause_schedule(schema_id)


def unpause_schema_schedule_for_staff(schema_id: UUID) -> StaffActionResult:
    return SchemaStaffActions.unpause_schedule(schema_id)


def recreate_schema_schedule_for_staff(schema_id: UUID) -> StaffActionResult:
    return SchemaStaffActions.recreate_schedule(schema_id)


def summarize_auto_disabled_schemas_for_staff(selection: AutoDisabledSchemaFilter) -> AutoDisabledSchemasSummary:
    return AutoDisabledSchemas.summary(selection)


def list_auto_disabled_schemas_for_staff(
    selection: AutoDisabledSchemaFilter, page_number: str | None
) -> AutoDisabledSchemasPage:
    return AutoDisabledSchemas.page(selection, page_number)


def select_auto_disabled_schemas_for_staff(selection: AutoDisabledSchemaFilter) -> AutoDisabledSchemaSelection:
    """The newest matching schemas, at most `MAX_REENABLE_PER_RUN`, for one re-enable run."""
    return AutoDisabledSchemas.select(selection)


def reenable_schemas_for_staff(
    targets: Sequence[SchemaReenableTarget], time_budget_seconds: float | None = None
) -> SchemaReenableResult:
    return AutoDisabledSchemas.reenable(targets, time_budget_seconds)
