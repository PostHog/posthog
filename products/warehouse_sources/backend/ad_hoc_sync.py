"""Start a single external-data-job run outside the schema's Temporal schedule.

The schedule's stored input is always billable, so a run that must not be charged, or that must
stage a reset first, cannot go through it. Operators reach this from Django admin; a bulk cleanup
reaches it from the `resync_schemas_non_billable` management command. Both share this module so the
pause, stage, start, and rollback sequence has one definition.
"""

import time

from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from posthog.dataclasses import frozen
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.facade.api import pause_external_data_schedule, unpause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


@frozen
class AdHocSyncTrigger:
    workflow_id: str
    # True only when this call paused the schedule, so the caller can say whether it will auto-unpause.
    schedule_paused_now: bool


class SchedulePauseError(Exception):
    """Pausing the schedule failed, so no run was started and nothing was staged."""


class WorkflowStartError(Exception):
    """The workflow failed to start. Any pause taken by this call has been rolled back."""


@async_to_sync
async def start_external_data_workflow(client: Client, workflow_id: str, inputs: ExternalDataWorkflowInputs) -> None:
    await client.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


@async_to_sync
async def is_schedule_paused(client: Client, schedule_id: str) -> bool:
    """Best-effort check whether the per-schema Temporal schedule is currently paused.

    Returns False if the schedule does not exist or describe fails — the caller
    treats that as 'no schedule to pause' and proceeds without pausing.
    """
    handle = client.get_schedule_handle(schedule_id)
    try:
        desc = await handle.describe()
    except Exception:
        return False
    return bool(desc.schedule.state.paused)


def trigger_ad_hoc_sync(
    client: Client,
    schema: ExternalDataSchema,
    *,
    billable: bool,
    reset_pipeline: bool,
    workflow_id_prefix: str,
) -> AdHocSyncTrigger:
    """Pause the schedule, stage the reset when asked, and start one run.

    Pausing comes first because Temporal's "OnlyOne" overlap policy is per-schedule, not across a
    schedule plus an ad-hoc workflow, so without it the scheduled run can race this one. A schedule
    the caller already paused by hand is left alone, so this does not undo their action.
    """
    was_paused = is_schedule_paused(client, str(schema.id))
    paused_now = False
    if not was_paused:
        try:
            pause_external_data_schedule(str(schema.id))
            paused_now = True
        except Exception as e:
            raise SchedulePauseError(str(e)) from e

    # Single save: the reset, the CDC re-snapshot, and the auto-unpause marker in one round-trip.
    # reset_pipeline goes on sync_type_config rather than the workflow input because the pipeline
    # pops it after the first reset; on the input every activity retry would re-read True and wipe
    # Delta plus the cursor, restarting from row 0.
    update_fields: list[str] = []
    if reset_pipeline:
        schema.sync_type_config["reset_pipeline"] = True
        update_fields.append("sync_type_config")
        # A streaming CDC schema no-ops a normal reset — CDCExtractionWorkflow owns it and the
        # per-schema run raises CDCHandledExternally. Flip it back to snapshot so this run does a
        # full re-snapshot. The job is created non-billable when the caller asks for that, and on
        # completion set_initial_sync_complete transitions it back to streaming, so ongoing CDC
        # stays billable. The save must precede the workflow start so the source reloads
        # cdc_mode="snapshot" instead of racing on stale "streaming".
        if schema.is_cdc and schema.cdc_mode == "streaming":
            schema.sync_type_config["cdc_mode"] = "snapshot"
            schema.sync_type_config.pop("cdc_last_log_position", None)
            schema.sync_type_config.pop("cdc_deferred_runs", None)
            schema.initial_sync_complete = False
            update_fields.append("initial_sync_complete")
    if paused_now:
        schema.sync_type_config["admin_unpause_schedule_after_run"] = True
        if "sync_type_config" not in update_fields:
            update_fields.append("sync_type_config")
    if update_fields:
        schema.save(update_fields=update_fields)

    inputs = ExternalDataWorkflowInputs(
        team_id=schema.team_id,
        external_data_source_id=schema.source.id,
        external_data_schema_id=schema.id,
        billable=billable,
        reset_pipeline=None,
    )
    workflow_id = f"{schema.id}-{workflow_id_prefix}-{int(time.time())}"
    try:
        start_external_data_workflow(client, workflow_id, inputs)
    except Exception as e:
        # Without this rollback a failed start leaves the schedule paused forever: the unpause
        # marker is only read by a workflow that never began, and the flag is orphaned in config.
        if paused_now:
            try:
                unpause_external_data_schedule(str(schema.id))
                schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                schema.save(update_fields=["sync_type_config"])
            except Exception:
                pass
        raise WorkflowStartError(str(e)) from e

    return AdHocSyncTrigger(workflow_id=workflow_id, schedule_paused_now=paused_now)
