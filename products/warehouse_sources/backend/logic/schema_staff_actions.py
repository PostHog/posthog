"""What staff see and do for one warehouse source or schema in PostHog Admin: partitioning, schedules, ad-hoc runs."""

import time
from typing import Any, assert_never, cast, get_args
from uuid import UUID

from django.core.paginator import Paginator

from posthog.dataclasses import frozen
from posthog.temporal.common.client import sync_connect
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.facade.api import (
    pause_external_data_schedule,
    sync_external_data_job_workflow,
    unpause_external_data_schedule,
)
from products.warehouse_sources.backend.ad_hoc_sync import (
    SchedulePauseError,
    SyncStillRunningError,
    WorkflowStartError,
    is_schedule_paused,
    start_external_data_workflow,
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
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)

# Source of truth lives in pipeline.typings. Re-deriving here keeps the choices in sync if a new format or mode is
# ever added.
PARTITION_FORMAT_CHOICES: tuple[str, ...] = get_args(PartitionFormat)
PARTITION_MODE_CHOICES: tuple[str, ...] = get_args(PartitionMode)

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


@frozen
class StagedRepartition:
    label: str
    target: dict[str, Any]


def _failed(message: str) -> StaffActionResult:
    return StaffActionResult(ok=False, message=message)


class SchemaStaffActions:
    """Each action returns what happened as one message, so the console can show it as is."""

    @staticmethod
    def _stage_repartition(schema: ExternalDataSchema, request: RepartitionRequest) -> StagedRepartition | str:
        """The `repartition_pending` target for the input, or why the input cannot be used."""
        # Mode comes from the form. It falls back to the schema's current mode for a pure in-place repartition, and
        # must resolve to a known mode: the pipeline picks one on the first sync, so before that staff choose.
        new_mode = request.partition_mode or schema.partition_mode
        if new_mode not in PARTITION_MODE_CHOICES:
            return (
                f"Invalid partition_mode: {new_mode!r}. Choose one of {', '.join(PARTITION_MODE_CHOICES)} "
                "(or run a sync first so the pipeline picks one)."
            )
        new_mode = cast(PartitionMode, new_mode)
        mode_changed = new_mode != schema.partition_mode

        # `staged` is only a validated carrier of the chosen knobs for the pending target below.
        staged: dict[str, Any] = {"partition_mode_override": new_mode}
        label_bits: list[str] = []
        if mode_changed:
            label_bits.append(f"partition_mode: {schema.partition_mode!r} → {new_mode!r}")

        # Keys are optional: omitting them keeps the existing keys (in-place repartition). When switching INTO
        # datetime or numerical they are required, because the existing composite PK is usually unsuitable for
        # single-column bucketing.
        keys = list(request.partitioning_keys)

        if new_mode == "datetime":
            if keys:
                if len(keys) != 1:
                    return (
                        "datetime mode needs exactly one partitioning key — the date/timestamp "
                        "column to bucket on (e.g. action_date)."
                    )
                staged["partitioning_keys_override"] = keys
                label_bits.append(f"keys={keys}")
            elif mode_changed:
                return (
                    "Switching to datetime needs exactly one partitioning key — the date/timestamp "
                    "column to bucket on (e.g. action_date)."
                )
            if request.partition_format not in PARTITION_FORMAT_CHOICES:
                return f"Invalid partition_format: {request.partition_format!r}."
            # partition_format already survives the reset and is read directly by the pipeline.
            staged["partition_format"] = request.partition_format
            label_bits.append(f"format={request.partition_format!r}")
        elif new_mode == "numerical":
            if keys:
                if len(keys) != 1:
                    return "numerical mode needs exactly one integer partitioning key."
                staged["partitioning_keys_override"] = keys
                label_bits.append(f"keys={keys}")
            elif mode_changed:
                return "Switching to numerical needs exactly one integer partitioning key."
            if request.partition_size is None:
                return "partition_size is required."
            staged["partition_size_override"] = request.partition_size
            label_bits.append(f"partition_size={request.partition_size}")
        elif new_mode == "md5":
            if request.partition_count is None:
                return "partition_count is required."
            if keys:
                staged["partitioning_keys_override"] = keys
                label_bits.append(f"keys={keys}")
            elif mode_changed:
                # Switching INTO md5: clear any stale keys override so md5 falls back to the table's primary keys
                # instead of a date column pinned by an earlier datetime attempt.
                staged["partitioning_keys_override"] = None
            staged["partition_count_override"] = request.partition_count
            label_bits.append(f"partition_count={request.partition_count}")
        else:
            # Exhaustive over PartitionMode, so mypy asks for an update here if a new mode is ever added.
            assert_never(new_mode)

        return StagedRepartition(
            label=", ".join(label_bits) if label_bits else "repartition",
            # The next run's pre-extraction activity rewrites the existing S3 data into this scheme in place: no
            # source re-pull, no reset.
            target={
                "partition_mode": new_mode,
                "partition_format": staged.get("partition_format"),
                "partition_count": staged.get("partition_count_override"),
                "partition_size": staged.get("partition_size_override"),
                "partition_keys": (
                    staged.get("partitioning_keys_override")
                    or schema.partitioning_keys
                    or schema.primary_key_columns
                    or []
                ),
                "trigger_reason": "admin",
                "attempts": 0,
            },
        )

    @classmethod
    def repartition(cls, schema_id: UUID, request: RepartitionRequest) -> StaffActionResult:
        # nosemgrep: idor-lookup-without-team -- staff-only console lookup by id behind admin_view
        schema = ExternalDataSchema.objects.select_related("source").filter(id=schema_id).first()
        if schema is None:
            return _failed(f"Schema {schema_id} not found.")
        staged = cls._stage_repartition(schema, request)
        if isinstance(staged, str):
            return _failed(staged)
        return cls._pause_save_and_resync(
            schema,
            staged_updates={"repartition_pending": staged.target},
            change_label=staged.label,
            workflow_kind="repartition",
            reset_pipeline=False,
        )

    @staticmethod
    def _pause_save_and_resync(
        schema: ExternalDataSchema,
        *,
        staged_updates: dict[str, Any],
        change_label: str,
        workflow_kind: str,
        reset_pipeline: bool = True,
    ) -> StaffActionResult:
        # Shared tail for the partition-tuning staff actions: pause the schedule, stage the sync_type_config
        # updates, and trigger a single non-billable run. With reset_pipeline=True the run re-pulls from source;
        # with False the run's pre-extraction activity repartitions in place from S3 (no source pull) before
        # syncing.
        #
        # Pause first so the scheduled workflow doesn't race with the staff one (Temporal's "OnlyOne" overlap
        # policy is per-schedule, not across schedule + ad-hoc workflow). If the schedule was already paused by
        # hand, skip auto-unpause so this does not undo that.
        try:
            client = sync_connect()
        except Exception as e:
            return _failed(f"Failed to connect to Temporal: {e}.")

        was_paused = is_schedule_paused(client, str(schema.id))
        admin_paused_now = False
        if not was_paused:
            try:
                pause_external_data_schedule(str(schema.id))
                admin_paused_now = True
            except Exception as e:
                return _failed(f"Failed to pause schedule before resync: {e}.")

        # Single save: stage the partition update(s), reset_pipeline, and the auto-unpause marker (read by
        # `resume_schedule_after_ad_hoc_run` when the run completes) in one round-trip. reset_pipeline goes on
        # sync_type_config rather than the workflow input so the pipeline can pop it after the first reset;
        # passing it on inputs makes every activity retry re-read True and wipe Delta + cursor, restarting from
        # row 0.
        for key, value in staged_updates.items():
            schema.sync_type_config[key] = value
        if reset_pipeline:
            schema.sync_type_config["reset_pipeline"] = True
        workflow_id = f"{schema.id}-admin-{workflow_kind}-{int(time.time())}"
        previous_marker = schema.sync_type_config.get("admin_unpause_schedule_after_run")
        if admin_paused_now or previous_marker:
            schema.sync_type_config["admin_unpause_schedule_after_run"] = workflow_id
        schema.save(update_fields=["sync_type_config"])

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=False,
            reset_pipeline=None,
        )
        try:
            start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            # Best-effort rollback of the pause taken above. Without this, a failed workflow start leaves the
            # schedule paused forever (the flag is read by the workflow at completion, and there's no workflow
            # if start failed) and the flag orphaned in sync_type_config.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
            elif previous_marker:
                try:
                    schema.sync_type_config["admin_unpause_schedule_after_run"] = previous_marker
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
            return _failed(
                f"Saved {change_label}, but failed to trigger run: {e}. "
                f"Trigger one manually before the next scheduled sync."
            )

        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if admin_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        run_note = (
            "non-billable reset resync (re-pulls from source)"
            if reset_pipeline
            else "non-billable in-place repartition (no source pull)"
        )
        return StaffActionResult(
            ok=True, message=f"{change_label}. Triggered {run_note} (workflow_id={workflow_id}).{pause_note}"
        )

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
