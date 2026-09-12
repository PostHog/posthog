"""External schema synchronization helpers."""

from typing import Any

import structlog
import temporalio

from products.data_warehouse.backend.facade.api import (
    cancel_external_data_workflow,
    sync_external_data_job_workflow,
    trigger_external_data_workflow,
)
from products.warehouse_sources.backend.facade.models import (
    ExternalDataJob,
    ExternalDataSchema,
    update_sync_type_config_keys,
)

logger = structlog.get_logger(__name__)


_CDC_WRITE_TARGETS_BY_TABLE_MODE: dict[str, frozenset[str]] = {
    "consolidated": frozenset({"consolidated"}),
    "cdc_only": frozenset({"cdc_history"}),
    "both": frozenset({"consolidated", "cdc_history"}),
}


def _cdc_table_mode_change_needs_resnapshot(old_mode: str | None, new_mode: str | None) -> bool:
    """True when the new mode adds a physical write target (consolidated and/or cdc history table)."""
    if old_mode == new_mode:
        return False
    old_targets = _CDC_WRITE_TARGETS_BY_TABLE_MODE.get(old_mode or "", frozenset())
    new_targets = _CDC_WRITE_TARGETS_BY_TABLE_MODE.get(new_mode or "", frozenset())
    return bool(new_targets - old_targets)


def _concrete_field_names(validated_data: dict[str, Any]) -> list[str]:
    """The schema columns this payload writes, for a save() that leaves every other column alone.

    updated_at is auto_now, and Django only refreshes an auto_now field named in update_fields.
    """
    columns = {field.name for field in ExternalDataSchema._meta.concrete_fields}
    return [*(key for key in validated_data if key in columns), "updated_at"]


def _reset_cdc_for_full_resnapshot(instance: ExternalDataSchema) -> None:
    """Cancel any running workflow and reset schema state so the next run does a full snapshot.

    Must save before triggering: the workflow reloads the schema and bails via
    `CDCHandledExternally` if it sees `cdc_mode='streaming'`.
    """
    latest_running_job = (
        ExternalDataJob.objects.filter(schema_id=instance.pk, team_id=instance.team_id).order_by("-created_at").first()
    )
    if latest_running_job and latest_running_job.workflow_id and latest_running_job.status == "Running":
        try:
            cancel_external_data_workflow(latest_running_job.workflow_id)
        except temporalio.service.RPCError as e:
            logger.exception(
                "Could not cancel running workflow before re-snapshot",
                schema_id=str(instance.id),
                exc_info=e,
            )

    # Merge under a row lock so the reset can't clobber a concurrent CDC extract activity's
    # sync_type_config writes (and the status/initial_sync_complete save below skips the JSON
    # column, leaving no second window for the merged config to be overwritten).
    instance.sync_type_config = update_sync_type_config_keys(
        instance.id,
        instance.team_id,
        updates={"reset_pipeline": True, "cdc_mode": "snapshot"},
        removes=["cdc_last_log_position", "cdc_deferred_runs"],
    )
    instance.initial_sync_complete = False
    instance.save(update_fields=["initial_sync_complete", "updated_at"])

    try:
        trigger_external_data_workflow(instance)
    except temporalio.service.RPCError as e:
        # Leave the status untouched so the Syncs UI doesn't show RUNNING for a workflow that never
        # started. The sync_type_config mutations stay; the schema's intent is still "do a
        # re-snapshot next run".
        logger.exception(
            "Could not trigger external data workflow after re-snapshot reset",
            schema_id=str(instance.id),
            exc_info=e,
        )
        return

    instance.status = ExternalDataSchema.Status.RUNNING
    instance.save(update_fields=["status", "updated_at"])


def _trigger_schema_sync(instance: ExternalDataSchema) -> None:
    """Trigger the schema's sync, creating its Temporal schedule first if it has none.

    A schema can reach the UI with no schedule behind it (never created, or dropped), and
    triggering one that isn't there raises NOT_FOUND. Retrying can't fix that, so recover the
    same way the source-level reload does instead of dead-ending a single table's sync.
    """
    try:
        trigger_external_data_workflow(instance)
    except temporalio.service.RPCError as e:
        if e.status != temporalio.service.RPCStatusCode.NOT_FOUND:
            raise
        sync_external_data_job_workflow(instance, create=True, should_sync=instance.should_sync)


# Sync frequencies below the 5-minute floor. No longer accepted as input (dropped from the
# serializer's choices), but rows written before the floor may still carry one until the
# migrate_sub_5min_sync_frequencies command bumps them — so the interval mappings keep parsing
# "1min" and the update path clamps instead of erroring.
LEGACY_SUB_FLOOR_SYNC_FREQUENCIES = {"1min"}

FLOOR_SYNC_FREQUENCY = "5min"
