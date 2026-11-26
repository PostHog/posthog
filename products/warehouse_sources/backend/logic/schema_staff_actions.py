"""What staff see and do for one warehouse source or schema in PostHog Admin: partitioning, schedules, ad-hoc runs."""

from uuid import UUID

from django.core.paginator import Paginator

from posthog.temporal.common.client import sync_connect

from products.data_warehouse.backend.facade.api import (
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    unpause_external_data_schedule,
)
from products.warehouse_sources.backend.ad_hoc_sync import (
    SchedulePauseError,
    SyncStillRunningError,
    WorkflowStartError,
    trigger_ad_hoc_sync,
)
from products.warehouse_sources.backend.facade.contracts import (
    RepartitionRequest,
    StaffActionResult,
    StaffJobRow,
    StaffJobsPage,
    StaffSchemaPartitioning,
    StaffSchemaRow,
    StaffSchemasPage,
    StaffSchemaSummary,
    StaffSourceSummary,
)
from products.warehouse_sources.backend.logic.partitioning import (
    PARTITION_FORMAT_CHOICES as PARTITION_FORMAT_CHOICES,
    PARTITION_MODE_CHOICES as PARTITION_MODE_CHOICES,
    stage_repartition,
)
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

JOBS_PER_PAGE = 20
SCHEMAS_PER_PAGE = 50


class SchemaStaffReads:
    @staticmethod
    def schema(schema_id: UUID) -> StaffSchemaSummary | None:
        # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
        schema = ExternalDataSchema.objects.select_related("source", "team", "table").filter(id=schema_id).first()
        if schema is None:
            return None
        return StaffSchemaSummary(
            id=schema.id,
            name=schema.name,
            team_id=schema.team_id,
            team_name=schema.team.name,
            source_id=schema.source_id,
            source_type=schema.source.source_type,
            is_cdc=schema.is_cdc,
            supports_scheduled_sync=schema.source.supports_scheduled_sync,
            partitioning=StaffSchemaPartitioning(
                enabled=schema.partitioning_enabled,
                mode=schema.partition_mode,
                format=schema.partition_format,
                size=schema.partition_size,
                count=schema.partition_count,
                count_override=schema.partition_count_override,
                size_override=schema.partition_size_override,
                mode_override=schema.partition_mode_override,
                keys_override=tuple(schema.partitioning_keys_override)
                if schema.partitioning_keys_override is not None
                else None,
                keys=tuple(schema.partitioning_keys) if schema.partitioning_keys is not None else None,
            ),
            # Known once the table has synced. Before the first sync staff type the keys by hand.
            available_columns=tuple(sorted((schema.table.columns or {}).keys()))
            if schema.table and schema.table.columns
            else None,
            should_sync=schema.should_sync,
            deleted=bool(schema.deleted),
            auto_disabled_at=schema.auto_disabled_at,
        )

    @staticmethod
    def jobs(schema_id: UUID, page_number: str | None) -> StaffJobsPage:
        jobs = ExternalDataJob.objects.filter(schema_id=schema_id).order_by("-created_at")
        page = Paginator(jobs, JOBS_PER_PAGE).get_page(page_number)
        return StaffJobsPage(
            rows=tuple(
                StaffJobRow(
                    id=job.id,
                    status=job.status,
                    created_at=job.created_at,
                    finished_at=job.finished_at,
                    rows_synced=job.rows_synced,
                    workflow_id=job.workflow_id,
                    workflow_run_id=job.workflow_run_id,
                    latest_error=job.latest_error,
                )
                for job in page
            ),
            number=page.number,
            num_pages=page.paginator.num_pages,
            count=page.paginator.count,
        )

    @staticmethod
    def source(source_id: UUID) -> StaffSourceSummary | None:
        source = (
            # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
            ExternalDataSource.objects.select_related(None)
            .select_related("team")
            .defer("job_inputs")
            .filter(id=source_id)
            .first()
        )
        if source is None:
            return None
        return StaffSourceSummary(
            id=source.id,
            source_type=source.source_type,
            prefix=source.prefix,
            team_id=source.team_id,
            team_name=source.team.name,
        )

    @staticmethod
    def source_schemas(source_id: UUID, page_number: str | None) -> StaffSchemasPage:
        # A relational source can carry hundreds of schemas, so the list is paginated.
        schemas = (
            ExternalDataSchema.objects.filter(source_id=source_id)
            .select_related("table")
            .defer("sync_type_config", "enabled_columns", "row_filters")
            .order_by("name", "id")
        )
        page = Paginator(schemas, SCHEMAS_PER_PAGE).get_page(page_number)
        return StaffSchemasPage(
            rows=tuple(
                StaffSchemaRow(
                    id=schema.id,
                    name=schema.name,
                    deleted=bool(schema.deleted),
                    status=schema.status,
                    should_sync=schema.should_sync,
                    sync_type=schema.sync_type,
                    sync_frequency_interval=schema.sync_frequency_interval,
                    last_synced_at=schema.last_synced_at,
                    table_id=schema.table.id if schema.table else None,
                    table_name=schema.table.name if schema.table else None,
                    table_row_count=schema.table.row_count if schema.table else None,
                    latest_error=schema.latest_error,
                )
                for schema in page
            ),
            number=page.number,
            num_pages=page.paginator.num_pages,
            count=page.paginator.count,
        )


def _failed(message: str) -> StaffActionResult:
    return StaffActionResult(ok=False, message=message)


class SchemaStaffActions:
    """Each action returns what happened as one message, so the console can show it as is."""

    @staticmethod
    def repartition(
        schema_id: UUID, request: RepartitionRequest, *, requested_by_id: int | None = None
    ) -> StaffActionResult:
        # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id).first()
        if schema is None:
            return _failed(f"Schema {schema_id} not found.")
        outcome = stage_repartition(schema, request, trigger_reason="admin", requested_by_id=requested_by_id)
        # A target that is staged but whose run did not start still reports a failure, so staff start one.
        return StaffActionResult(ok=outcome.run_started, message=outcome.message)

    @staticmethod
    def trigger_sync(schema_id: UUID, *, billable: bool, reset_pipeline: bool) -> StaffActionResult:
        # Bypasses the schedule because the schedule's stored input cannot override `billable` per trigger.
        # `trigger_ad_hoc_sync` pauses the schedule first and lets `resume_schedule_after_ad_hoc_run` resume it.
        # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id).first()
        if schema is None:
            return _failed(f"Schema {schema_id} not found.")

        try:
            client = sync_connect()
        except Exception as e:
            return _failed(f"Failed to connect to Temporal: {e}.")

        try:
            trigger = trigger_ad_hoc_sync(
                client,
                schema,
                billable=billable,
                reset_pipeline=reset_pipeline,
                workflow_id_prefix="admin-resync",
            )
        except SchedulePauseError as e:
            return _failed(f"Failed to pause schedule before sync: {e}.")
        except WorkflowStartError as e:
            return _failed(f"Failed to trigger sync: {e}")
        except SyncStillRunningError as e:
            return _failed(str(e))

        billable_label = "billable" if billable else "non-billable"
        action_label = "resync (with reset)" if reset_pipeline else "sync"
        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if trigger.schedule_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        return StaffActionResult(
            ok=True,
            message=f"Triggered {billable_label} {action_label} for {schema.name} "
            f"(workflow_id={trigger.workflow_id}).{pause_note}",
        )

    @staticmethod
    def pause_schedule(schema_id: UUID) -> StaffActionResult:
        try:
            pause_external_data_schedule(str(schema_id))
        except Exception as e:
            return _failed(f"Failed to pause schedule: {e}")
        return StaffActionResult(ok=True, message="Schedule paused. Remember to unpause when admin work is done.")

    @staticmethod
    def unpause_schedule(schema_id: UUID) -> StaffActionResult:
        try:
            unpause_external_data_schedule(str(schema_id))
        except Exception as e:
            return _failed(f"Failed to unpause schedule: {e}")
        return StaffActionResult(ok=True, message="Schedule unpaused.")

    @staticmethod
    def recreate_schedule(schema_id: UUID) -> StaffActionResult:
        # Recovery for schemas whose per-schema Temporal schedule is missing (e.g. the source creation request was
        # killed between committing the rows and creating the schedules, or the schema was resurrected after a
        # soft-delete). Safe on an existing schedule too: sync_external_data_job_workflow falls back to updating it
        # in place. Deliberately does NOT trigger a run: the schedule's stored action is always billable, so staff
        # start an immediate run with "Trigger sync" instead, which is non-billable by default.
        # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id).first()
        if schema is None:
            return _failed(f"Schema {schema_id} not found.")

        if not schema.source.supports_scheduled_sync:
            return _failed("This source is queried directly and does not use per-schema sync schedules.")

        try:
            sync_external_data_job_workflow(
                schema, create=True, should_sync=schema.should_sync, trigger_immediately=False
            )
        except Exception as e:
            return _failed(f"Failed to recreate schedule: {e}")

        paused_note = (
            " The schedule was created paused because sync is disabled for this schema."
            if not schema.should_sync
            else ""
        )
        return StaffActionResult(
            ok=True,
            message=f"Recreated Temporal schedule for {schema.name}. No run was triggered; "
            f'use "Trigger sync" for an immediate non-billable run.{paused_note}',
        )
