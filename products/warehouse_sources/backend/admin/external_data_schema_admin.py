import time
from typing import Any, assert_never, get_args

from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy

from posthog.temporal.common.client import sync_connect
from posthog.temporal.utils import ExternalDataWorkflowInputs

from products.data_warehouse.backend.facade.api import pause_external_data_schedule, unpause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    PartitionFormat,
    PartitionMode,
)

# Source of truth lives in pipeline.typings. Re-deriving here keeps the dropdowns in
# sync if a new format / mode is ever added.
PARTITION_FORMAT_CHOICES: tuple[str, ...] = get_args(PartitionFormat)
PARTITION_MODE_CHOICES: tuple[str, ...] = get_args(PartitionMode)


@async_to_sync
async def _start_external_data_workflow(client: Client, workflow_id: str, inputs: ExternalDataWorkflowInputs) -> None:
    await client.start_workflow(
        "external-data-job",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.DATA_WAREHOUSE_TASK_QUEUE,
    )


@async_to_sync
async def _is_schedule_paused(client: Client, schedule_id: str) -> bool:
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


def _change_url(schema_id) -> str:
    return reverse("admin:warehouse_sources_externaldataschema_change", args=[schema_id])


def _parse_positive_int(request, field: str, label: str) -> int | None:
    """Parse a required positive integer from POST, posting a flash message on failure.

    Returns the parsed value, or None if the field is empty / not an integer / < 1
    (after posting the appropriate `messages.error`). Callers redirect back to the
    change page when None is returned. Shared by the repartition and change-partition-mode
    views, whose forms both take operator-typed partition counts/sizes.
    """
    raw = request.POST.get(field, "").strip()
    if not raw:
        messages.error(request, f"{label} is required.")
        return None
    try:
        value = int(raw)
    except ValueError:
        messages.error(request, f"{label} must be an integer; got {raw!r}.")
        return None
    if value < 1:
        messages.error(request, f"{label} must be >= 1; got {value}.")
        return None
    return value


@admin.register(ExternalDataSchema)
class ExternalDataSchemaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "status",
        "should_sync",
        "sync_type",
        "source_type",
        "team_link",
        "last_synced_at",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("team", "team__organization", "source")
    list_filter = ("status", "should_sync", "sync_type")
    search_fields = ("id", "name", "team__name", "team__organization__name")
    autocomplete_fields = ("team",)
    raw_id_fields = ("table", "source")
    readonly_fields = ("table", "source", "created_by")
    ordering = ("-created_at",)

    change_form_template = "admin/data_warehouse/externaldataschema/change_form.html"

    JOBS_PER_PAGE = 20

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<uuid:schema_id>/repartition/",
                self.admin_site.admin_view(self.repartition_view),
                name="external_data_schema_repartition",
            ),
            path(
                "<uuid:schema_id>/change-partition-mode/",
                self.admin_site.admin_view(self.change_partition_mode_view),
                name="external_data_schema_change_partition_mode",
            ),
            path(
                "<uuid:schema_id>/trigger-sync/",
                self.admin_site.admin_view(self.trigger_sync_view),
                name="external_data_schema_trigger_sync",
            ),
            path(
                "<uuid:schema_id>/pause-schedule/",
                self.admin_site.admin_view(self.pause_schedule_view),
                name="external_data_schema_pause_schedule",
            ),
            path(
                "<uuid:schema_id>/unpause-schedule/",
                self.admin_site.admin_view(self.unpause_schedule_view),
                name="external_data_schema_unpause_schedule",
            ),
        ]
        return custom_urls + urls

    def repartition_view(self, request, schema_id):
        # Update the partition knob that matches the schema's partition_mode AND
        # immediately trigger a non-billable resync with reset_pipeline=True.
        # Repartition without a reset risks mixing old/new partition layouts in
        # the same Delta table, which corrupts the data with no easy way to
        # recover — so the two actions are bundled.
        #
        # We require an explicit partition_mode on the schema. The pipeline picks
        # the mode the first time a table is partitioned (based on column shape);
        # forcing a mode here would cause the next sync to crash if the table
        # doesn't carry a column compatible with that mode.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:warehouse_sources_externaldataschema_changelist"))

        if schema.partition_mode is None:
            messages.error(
                request,
                "Schema has no partition_mode set. Run a sync first so the pipeline can pick "
                "the appropriate mode for this table, then come back to repartition.",
            )
            return redirect(_change_url(schema_id))

        # Validate input by mode and stage the value to write. We defer the actual
        # save so we can do one DB write that updates the partition knob AND sets
        # reset_pipeline AND records whether to auto-unpause the schedule.
        partition_field: str
        partition_value: Any
        previous_value: Any
        if schema.partition_mode == "datetime":
            new_format = request.POST.get("partition_format")
            if new_format not in PARTITION_FORMAT_CHOICES:
                messages.error(request, f"Invalid partition_format: {new_format!r}.")
                return redirect(_change_url(schema_id))
            partition_field = "partition_format"
            partition_value = new_format
            previous_value = schema.partition_format
        elif schema.partition_mode == "numerical":
            new_size = _parse_positive_int(request, "partition_size", "partition_size")
            if new_size is None:
                return redirect(_change_url(schema_id))
            # Write the *_override key, not partition_size directly: the bundled reset below
            # wipes partition_size, so a plain write would be discarded and the source would
            # re-derive its own value. The override survives the reset and is consumed once
            # applied (see ExternalDataSchema.set_partitioning_enabled).
            partition_field = "partition_size_override"
            partition_value = new_size
            previous_value = schema.partition_size
        elif schema.partition_mode == "md5":
            new_count = _parse_positive_int(request, "partition_count", "partition_count")
            if new_count is None:
                return redirect(_change_url(schema_id))
            # Write the *_override key (survives the reset); see the numerical branch above.
            partition_field = "partition_count_override"
            partition_value = new_count
            previous_value = schema.partition_count
        else:
            # Exhaustive over PartitionMode after the None check above; assert_never
            # makes mypy happy and crashes loudly if a new mode is added without
            # updating this view.
            assert_never(schema.partition_mode)

        # Display the logical knob name (without the _override suffix). *_override keys are
        # one-shot (consumed on the next reset); partition_format (datetime mode) survives every
        # reset, so the "pinned for this reset" note only applies to the override variants.
        display_field = partition_field.removesuffix("_override")
        pin_note = " (pinned for this reset)" if partition_field.endswith("_override") else ""
        change_label = f"{display_field}: {previous_value!r} → {partition_value!r}{pin_note}"

        return self._pause_save_and_resync(
            request,
            schema,
            staged_updates={partition_field: partition_value},
            change_label=change_label,
            workflow_kind="repartition",
        )

    def _pause_save_and_resync(
        self,
        request,
        schema: ExternalDataSchema,
        *,
        staged_updates: dict[str, Any],
        change_label: str,
        workflow_kind: str,
    ):
        # Shared tail for the partition-tuning admin actions (repartition, change partition mode):
        # pause the schedule, stage the operator's sync_type_config updates alongside
        # reset_pipeline, and trigger a single non-billable reset resync.
        #
        # Pause first so the scheduled workflow doesn't race with the admin one (Temporal's
        # "OnlyOne" overlap policy is per-schedule, not across schedule + ad-hoc workflow). If
        # the schedule was already paused (operator paused it manually beforehand), skip
        # auto-unpause so we don't undo their action.
        try:
            client = sync_connect()
        except Exception as e:
            messages.error(request, f"Failed to connect to Temporal: {e}.")
            return redirect(_change_url(schema.id))

        was_paused = _is_schedule_paused(client, str(schema.id))
        admin_paused_now = False
        if not was_paused:
            try:
                pause_external_data_schedule(str(schema.id))
                admin_paused_now = True
            except Exception as e:
                messages.error(request, f"Failed to pause schedule before resync: {e}.")
                return redirect(_change_url(schema.id))

        # Single save: stage the partition update(s), reset_pipeline, and the auto-unpause
        # marker (read by `update_external_data_job_model` at workflow end) in one round-trip.
        # reset_pipeline goes on sync_type_config rather than the workflow input so the pipeline
        # can pop it after the first reset; passing it on inputs makes every activity retry
        # re-read True and wipe Delta + cursor, restarting from row 0.
        for key, value in staged_updates.items():
            schema.sync_type_config[key] = value
        schema.sync_type_config["reset_pipeline"] = True
        if admin_paused_now:
            schema.sync_type_config["admin_unpause_schedule_after_run"] = True
        schema.save(update_fields=["sync_type_config"])

        inputs = ExternalDataWorkflowInputs(
            team_id=schema.team_id,
            external_data_source_id=schema.source.id,
            external_data_schema_id=schema.id,
            billable=False,
            reset_pipeline=None,
        )
        workflow_id = f"{schema.id}-admin-{workflow_kind}-{int(time.time())}"
        try:
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            # Best-effort rollback of the pause we just did. Without this, a failed
            # workflow start leaves the schedule paused forever (the flag is read
            # by the workflow at completion, and there's no workflow if start
            # failed) and the flag orphaned in sync_type_config.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
            messages.error(
                request,
                f"Saved {change_label}, but failed to trigger reset resync: {e}. "
                f"Trigger one manually before the next scheduled sync.",
            )
            return redirect(_change_url(schema.id))

        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if admin_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        messages.success(
            request,
            f"{change_label}. Triggered non-billable reset resync (workflow_id={workflow_id}).{pause_note}",
        )
        return redirect(_change_url(schema.id))

    def change_partition_mode_view(self, request, schema_id):
        # Switch a schema's partition *mode* (md5 / numerical / datetime) and immediately trigger a
        # non-billable reset resync, mirroring repartition_view's bundled-reset machinery. The
        # repartition action only tunes the knob *within* the current mode; this one changes the
        # mode itself — e.g. moving a table with a date column in its composite PK from md5 (which
        # scatters every change across all buckets) to datetime on that column (bounded,
        # prunable partitions).
        #
        # The chosen mode/keys are written as *_override keys that survive the bundled reset (which
        # wipes the auto-detected partition_mode/partitioning_keys) and are consumed once applied —
        # same one-shot semantics as the count/size overrides.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:warehouse_sources_externaldataschema_changelist"))

        if not self.has_change_permission(request, schema):
            raise PermissionDenied

        new_mode = request.POST.get("partition_mode")
        if new_mode not in get_args(PartitionMode):
            messages.error(
                request,
                f"Invalid partition_mode: {new_mode!r}. Choose one of {', '.join(get_args(PartitionMode))}.",
            )
            return redirect(_change_url(schema_id))

        staged: dict[str, Any] = {"partition_mode_override": new_mode}
        label_bits = [f"partition_mode: {schema.partition_mode!r} → {new_mode!r}"]

        # partitioning_keys: required for datetime/numerical (the single column to bucket on);
        # optional for md5 (defaults to the table's primary keys). Comma-separated input.
        raw_keys = request.POST.get("partitioning_keys", "").strip()
        keys = [k.strip() for k in raw_keys.split(",") if k.strip()]

        if new_mode == "datetime":
            if len(keys) != 1:
                messages.error(
                    request,
                    "datetime mode needs exactly one partitioning key — the date/timestamp column "
                    "to bucket on (e.g. action_date).",
                )
                return redirect(_change_url(schema_id))
            new_format = request.POST.get("partition_format")
            if new_format not in PARTITION_FORMAT_CHOICES:
                messages.error(request, f"Invalid partition_format: {new_format!r}.")
                return redirect(_change_url(schema_id))
            staged["partitioning_keys_override"] = keys
            # partition_format already survives the reset and is read directly by the pipeline.
            staged["partition_format"] = new_format
            label_bits.append(f"keys={keys}")
            label_bits.append(f"format={new_format!r}")
        elif new_mode == "numerical":
            if len(keys) != 1:
                messages.error(request, "numerical mode needs exactly one integer partitioning key.")
                return redirect(_change_url(schema_id))
            new_size = _parse_positive_int(request, "partition_size", "partition_size")
            if new_size is None:
                return redirect(_change_url(schema_id))
            staged["partitioning_keys_override"] = keys
            staged["partition_size_override"] = new_size
            label_bits.append(f"keys={keys}")
            label_bits.append(f"partition_size={new_size}")
        else:  # md5
            new_count = _parse_positive_int(request, "partition_count", "partition_count")
            if new_count is None:
                return redirect(_change_url(schema_id))
            # Always stage partitioning_keys_override (None when no keys supplied) so a stale
            # override from a prior change-mode action — e.g. the date column pinned by an earlier
            # datetime attempt — is explicitly cleared rather than silently winning the
            # `partitioning_keys_override or partitioning_keys or …` precedence chain and making md5
            # hash the wrong column. md5 defaults to the table's primary keys when this is None.
            staged["partitioning_keys_override"] = keys if keys else None
            if keys:
                label_bits.append(f"keys={keys}")
            staged["partition_count_override"] = new_count
            label_bits.append(f"partition_count={new_count}")

        change_label = ", ".join(label_bits) + " (pinned for this reset)"
        return self._pause_save_and_resync(
            request,
            schema,
            staged_updates=staged,
            change_label=change_label,
            workflow_kind="change-partition-mode",
        )

    def trigger_sync_view(self, request, schema_id):
        # Ad-hoc external-data-job workflow execution. Bypasses the schedule because
        # the schedule's stored input cannot override `billable` per-trigger. To avoid
        # racing with the regular scheduled run, mirror repartition_view: pause the
        # schedule (if not already paused), record the auto-unpause marker, and let
        # `update_external_data_job_model` resume the schedule on COMPLETED.
        if request.method != "POST":
            return redirect(_change_url(schema_id))

        try:
            schema = ExternalDataSchema.objects.select_related("source").get(id=schema_id)
        except ExternalDataSchema.DoesNotExist:
            messages.error(request, f"Schema {schema_id} not found.")
            return redirect(reverse("admin:warehouse_sources_externaldataschema_changelist"))

        # Both checkboxes default to off: an unchecked checkbox isn't sent in the
        # POST body, so .get() returns None, and `None == "on"` is False.
        reset_pipeline = request.POST.get("reset_pipeline") == "on"
        billable = request.POST.get("billable") == "on"

        try:
            client = sync_connect()
        except Exception as e:
            messages.error(request, f"Failed to connect to Temporal: {e}.")
            return redirect(_change_url(schema_id))

        was_paused = _is_schedule_paused(client, str(schema.id))
        admin_paused_now = False
        if not was_paused:
            try:
                pause_external_data_schedule(str(schema.id))
                admin_paused_now = True
            except Exception as e:
                messages.error(request, f"Failed to pause schedule before sync: {e}.")
                return redirect(_change_url(schema_id))

        # Single save: stage reset_pipeline (only when ticked) + the auto-unpause
        # marker. reset_pipeline goes on sync_type_config rather than the workflow
        # input — the pipeline pops it after the first reset; on the input it
        # would re-fire on every activity retry and wipe progress.
        update_fields: list[str] = []
        if reset_pipeline:
            schema.sync_type_config["reset_pipeline"] = True
            update_fields.append("sync_type_config")
            # A streaming CDC schema no-ops a normal reset — CDCExtractionWorkflow owns it and the
            # per-schema run raises CDCHandledExternally. Flip it back to snapshot so this run does a
            # full re-snapshot, mirroring ExternalDataSchemaViewSet.reset. The job below is created
            # billable=False, and on completion set_initial_sync_complete transitions it back to
            # streaming, so ongoing CDC stays billable. The save must precede the workflow start so
            # the source reloads cdc_mode="snapshot" instead of racing on stale "streaming".
            if schema.is_cdc and schema.cdc_mode == "streaming":
                schema.sync_type_config["cdc_mode"] = "snapshot"
                schema.sync_type_config.pop("cdc_last_log_position", None)
                schema.sync_type_config.pop("cdc_deferred_runs", None)
                schema.initial_sync_complete = False
                update_fields.append("initial_sync_complete")
        if admin_paused_now:
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
        workflow_id = f"{schema.id}-admin-resync-{int(time.time())}"
        try:
            _start_external_data_workflow(client, workflow_id, inputs)
        except Exception as e:
            # Best-effort rollback of the pause we just did so the schedule doesn't
            # stay paused forever after a failed workflow start.
            if admin_paused_now:
                try:
                    unpause_external_data_schedule(str(schema.id))
                    schema.sync_type_config.pop("admin_unpause_schedule_after_run", None)
                    schema.save(update_fields=["sync_type_config"])
                except Exception:
                    pass
            messages.error(request, f"Failed to trigger sync: {e}")
            return redirect(_change_url(schema_id))

        billable_label = "billable" if billable else "non-billable"
        action_label = "resync (with reset)" if reset_pipeline else "sync"
        pause_note = (
            " Schedule paused for the duration of this run; will auto-unpause on a successful completion."
            if admin_paused_now
            else " Schedule was already paused; leaving it paused."
        )
        messages.success(
            request,
            f"Triggered {billable_label} {action_label} for {schema.name} (workflow_id={workflow_id}).{pause_note}",
        )
        return redirect(_change_url(schema_id))

    def pause_schedule_view(self, request, schema_id):
        if request.method != "POST":
            return redirect(_change_url(schema_id))
        try:
            pause_external_data_schedule(str(schema_id))
            messages.success(request, "Schedule paused. Remember to unpause when admin work is done.")
        except Exception as e:
            messages.error(request, f"Failed to pause schedule: {e}")
        return redirect(_change_url(schema_id))

    def unpause_schedule_view(self, request, schema_id):
        if request.method != "POST":
            return redirect(_change_url(schema_id))
        try:
            unpause_external_data_schedule(str(schema_id))
            messages.success(request, "Schedule unpaused.")
        except Exception as e:
            messages.error(request, f"Failed to unpause schedule: {e}")
        return redirect(_change_url(schema_id))

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            jobs_qs = ExternalDataJob.objects.filter(schema=obj).order_by("-created_at")
            paginator = Paginator(jobs_qs, self.JOBS_PER_PAGE)
            page_number = request.GET.get("page", 1)
            page_obj = paginator.get_page(page_number)

            extra_context["page_obj"] = page_obj
            extra_context["temporal_ui_host"] = settings.TEMPORAL_UI_HOST
            extra_context["temporal_namespace"] = settings.TEMPORAL_NAMESPACE
            extra_context["site_url"] = settings.SITE_URL
            extra_context["team_id"] = obj.team_id

            extra_context["partition_format_choices"] = PARTITION_FORMAT_CHOICES
            extra_context["partition_mode_choices"] = PARTITION_MODE_CHOICES
            extra_context["current_partition_format"] = obj.partition_format
            extra_context["current_partition_mode"] = obj.partition_mode
            extra_context["current_partition_keys"] = obj.partitioning_keys
            extra_context["current_partition_size"] = obj.partition_size
            extra_context["current_partition_count"] = obj.partition_count
            extra_context["current_partition_count_override"] = obj.partition_count_override
            extra_context["current_partition_size_override"] = obj.partition_size_override
            extra_context["current_partition_mode_override"] = obj.partition_mode_override
            extra_context["current_partitioning_keys_override"] = obj.partitioning_keys_override
            extra_context["partitioning_enabled"] = obj.partitioning_enabled
            extra_context["repartition_url"] = reverse("admin:external_data_schema_repartition", args=[obj.id])
            extra_context["change_partition_mode_url"] = reverse(
                "admin:external_data_schema_change_partition_mode", args=[obj.id]
            )
            extra_context["trigger_sync_url"] = reverse("admin:external_data_schema_trigger_sync", args=[obj.id])
            extra_context["pause_schedule_url"] = reverse("admin:external_data_schema_pause_schedule", args=[obj.id])
            extra_context["unpause_schedule_url"] = reverse(
                "admin:external_data_schema_unpause_schedule", args=[obj.id]
            )

            # CDC schemas stream via a source-level extraction schedule; the per-schema schedule
            # above is paused once streaming starts, so surface the real one too.
            if obj.is_cdc:
                extra_context["cdc_extraction_schedule_id"] = f"cdc-extraction-{obj.source_id}"
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description="Team")
    def team_link(self, schema: ExternalDataSchema):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_team_change", args=[schema.team.pk]),
            schema.team.name,
        )

    @admin.display(description="Source type")
    def source_type(self, schema: ExternalDataSchema):
        return schema.source.source_type
