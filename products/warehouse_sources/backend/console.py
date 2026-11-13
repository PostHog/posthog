from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

from posthog.admin.console.panels import Owner, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Paging, Row, Table, ToolOperation

from products.warehouse_sources.backend.facade.contracts import (
    RepartitionRequest,
    StaffActionResult,
    StaffSchemaSummary,
    StaffSourceSummary,
)
from products.warehouse_sources.backend.facade.staff import (
    PARTITION_FORMAT_CHOICES,
    PARTITION_MODE_CHOICES,
    get_schema_for_staff,
    get_source_for_staff,
    list_schema_jobs_for_staff,
    list_source_schemas_for_staff,
    pause_schema_schedule_for_staff,
    recreate_schema_schedule_for_staff,
    repartition_schema_for_staff,
    trigger_schema_sync_for_staff,
    unpause_schema_schedule_for_staff,
)

WAREHOUSE_SOURCES = Owner(name="Warehouse sources", crest="warehouse-sources")
TOOL_KEY = "warehouse-sources"

STATUS_TONES = {
    "Running": Tone.INFO,
    "Completed": Tone.SUCCESS,
    "Failed": Tone.DESTRUCTIVE,
    "BillingLimitReached": Tone.WARNING,
    "BillingLimitTooLow": Tone.WARNING,
}
STATUS_LABELS = {
    "BillingLimitReached": "Billing limit reached",
    "BillingLimitTooLow": "Billing limit too low",
}
ERROR_PREVIEW_LENGTH = 80
ERROR_SEARCH_LENGTH = 200


def _truncate(text: str, length: int) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"


def _time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value is not None else "—"


def _status_cell(status: str | None) -> Cell:
    if not status:
        return Cell(text="—", muted=True)
    return Cell(text=STATUS_LABELS.get(status, status), tone=STATUS_TONES.get(status, Tone.DEFAULT))


def _tool_url(**params: str) -> str:
    return f"{reverse('admin_console_tool', kwargs={'tool_key': TOOL_KEY})}?{urlencode(params)}"


def _team_url(team_id: int) -> str:
    return reverse("admin_console_team", kwargs={"pk": team_id})


def _temporal_url(path: str) -> str:
    return f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/{path}"


def _uuid_param(request: HttpRequest, name: str) -> UUID | None:
    try:
        return UUID(request.GET.get(name, "").strip())
    except ValueError:
        return None


def _paging(number: int, num_pages: int, count: int, noun: str, **params: str) -> Paging:
    return Paging(
        number=number,
        num_pages=num_pages,
        summary=f"{count} {noun} in total",
        previous_url=_tool_url(**params, page=str(number - 1)) if number > 1 else None,
        next_url=_tool_url(**params, page=str(number + 1)) if number < num_pages else None,
    )


class SchemaPage:
    @staticmethod
    def partitioning(schema: StaffSchemaSummary) -> Table:
        partitioning = schema.partitioning
        rows: list[tuple[str, object]] = [
            ("partitioning_enabled", partitioning.enabled),
            ("partition_mode", partitioning.mode),
            ("partition_format", partitioning.format),
            ("partition_size", partitioning.size),
            ("partition_count", partitioning.count),
        ]
        pinned = [
            ("partition_count_override", partitioning.count_override),
            ("partition_size_override", partitioning.size_override),
            ("partition_mode_override", partitioning.mode_override),
            ("partitioning_keys_override", list(partitioning.keys_override) if partitioning.keys_override else None),
        ]
        rows.extend((name, f"{value} (pinned, applies on next reset)") for name, value in pinned if value is not None)
        rows.append(("partitioning_keys", list(partitioning.keys) if partitioning.keys else None))
        return Table(
            columns=("Partition setting", "Value"),
            rows=tuple(Row(cells=(Cell(text=name), Cell(text=str(value), mono=True))) for name, value in rows),
        )

    @staticmethod
    def schedules(schema: StaffSchemaSummary) -> Table:
        rows = [
            Row(
                cells=(
                    Cell(text="Schema schedule"),
                    Cell(text="View in Temporal ↗", href=_temporal_url(f"schedules/{schema.id}")),
                )
            )
        ]
        if schema.is_cdc:
            # CDC capture runs on a source-level schedule, and the schema schedule loads what capture buffered.
            rows.append(
                Row(
                    cells=(
                        Cell(text="CDC extraction schedule"),
                        Cell(
                            text="View in Temporal ↗",
                            href=_temporal_url(f"schedules/cdc-extraction-{schema.source_id}"),
                        ),
                    )
                )
            )
        return Table(columns=("Temporal schedule", "Link"), rows=tuple(rows))

    @staticmethod
    def jobs(schema: StaffSchemaSummary, page_number: str | None) -> tuple[Table, Paging]:
        page = list_schema_jobs_for_staff(schema.id, page_number)
        rows = []
        for job in page.rows:
            error = job.latest_error or ""
            rows.append(
                Row(
                    cells=(
                        Cell(text=str(job.id), mono=True),
                        _status_cell(job.status),
                        Cell(text=_time(job.created_at)),
                        Cell(text=_time(job.finished_at)),
                        Cell(text=str(job.rows_synced) if job.rows_synced is not None else "—"),
                        Cell(
                            text="View workflow ↗",
                            href=_temporal_url(f"workflows/{job.workflow_id}/{job.workflow_run_id}"),
                        )
                        if job.workflow_id and job.workflow_run_id
                        else Cell(text="—", muted=True),
                        Cell(
                            text="View logs ↗",
                            href=f"/project/{schema.team_id}/logs?{urlencode({'searchTerm': job.workflow_id})}",
                        )
                        if job.workflow_id
                        else Cell(text="—", muted=True),
                        Cell(text=_truncate(error, ERROR_PREVIEW_LENGTH)) if error else Cell(text="—", muted=True),
                        Cell(
                            text="View in error tracking ↗",
                            href=f"/project/{schema.team_id}/error-tracking?"
                            f"{urlencode({'searchQuery': _truncate(error, ERROR_SEARCH_LENGTH)})}",
                        )
                        if error
                        else Cell(text="—", muted=True),
                    )
                )
            )
        table = Table(
            columns=(
                "Job ID",
                "Status",
                "Created at",
                "Finished at",
                "Rows synced",
                "Temporal workflow",
                "Logs",
                "Error",
                "Error tracking",
            ),
            rows=tuple(rows),
            empty_text="No jobs found for this schema.",
        )
        return table, _paging(page.number, page.num_pages, page.count, "jobs", schema=str(schema.id))

    @classmethod
    def build(cls, schema: StaffSchemaSummary, page_number: str | None) -> Page:
        jobs, paging = cls.jobs(schema, page_number)
        return Page(
            blocks=(
                Notice(
                    text=f"Schema {schema.name} ({schema.id}) of a {schema.source_type} source, team "
                    f"{schema.team_name} ({schema.team_id}).",
                    link_text="All schemas of this source",
                    href=_tool_url(source=str(schema.source_id)),
                ),
                Notice(
                    text=(
                        "The scheduled sync uses Temporal's OnlyOne overlap policy, but ad-hoc runs bypass the "
                        "schedule and can race it. Pause the schedule before repartition or trigger sync work, "
                        "then unpause it when you finish."
                    ),
                    link_text="Open the team",
                    href=_team_url(schema.team_id),
                ),
                cls.partitioning(schema),
                cls.schedules(schema),
                jobs,
                paging,
            )
        )


class SourcePage:
    @staticmethod
    def build(source: StaffSourceSummary, page_number: str | None) -> Page:
        page = list_source_schemas_for_staff(source.id, page_number)
        rows = []
        for schema in page.rows:
            rows.append(
                Row(
                    cells=(
                        Cell(text=str(schema.id), href=_tool_url(schema=str(schema.id)), mono=True),
                        Cell(text=f"{schema.name} (deleted)" if schema.deleted else schema.name),
                        _status_cell(schema.status),
                        Cell(text="Yes" if schema.should_sync else "No"),
                        Cell(text=schema.sync_type or "—"),
                        Cell(text=str(schema.sync_frequency_interval or "—")),
                        Cell(text=_time(schema.last_synced_at)),
                        Cell(text=str(schema.table_row_count) if schema.table_row_count is not None else "—"),
                        Cell(
                            text=schema.table_name or "",
                            href=reverse("admin:warehouse_sources_datawarehousetable_change", args=[schema.table_id]),
                        )
                        if schema.table_id
                        else Cell(text="—", muted=True),
                        Cell(text=_truncate(schema.latest_error, ERROR_PREVIEW_LENGTH))
                        if schema.latest_error
                        else Cell(text="—", muted=True),
                    )
                )
            )
        return Page(
            blocks=(
                Notice(
                    text=f"{source.source_type} source {source.prefix or ''} ({source.id}), team {source.team_name} "
                    f"({source.team_id}).",
                    link_text="Open the team",
                    href=_team_url(source.team_id),
                ),
                Table(
                    columns=(
                        "Schema ID",
                        "Name",
                        "Status",
                        "Sync enabled",
                        "Sync type",
                        "Frequency",
                        "Last synced at",
                        "Table rows",
                        "Table",
                        "Latest error",
                    ),
                    rows=tuple(rows),
                    empty_text="No schemas found for this source.",
                ),
                _paging(page.number, page.num_pages, page.count, "schemas", source=str(source.id)),
            )
        )


class RepartitionForm(forms.Form):
    partition_mode = forms.ChoiceField(
        choices=[("", "Keep the current mode"), *((mode, mode) for mode in PARTITION_MODE_CHOICES)],
        required=False,
        help_text=(
            "Keep the mode and change only its setting to repartition in place. Change the mode to switch strategy, "
            "most often md5 to datetime on a date column of the primary key. The pipeline picks datetime by itself "
            "only for columns named created_at or inserted_at."
        ),
    )
    partitioning_keys = forms.CharField(
        label="Partitioning keys",
        required=False,
        help_text=(
            "Comma-separated column names. md5 hashes one or more keys together. datetime and numerical use one "
            "column. Leave empty to keep the current keys, or for md5 to use the table's primary keys."
        ),
    )
    partition_format = forms.ChoiceField(
        choices=[(value, value) for value in PARTITION_FORMAT_CHOICES],
        required=False,
        help_text="For datetime mode only.",
    )
    partition_count = forms.IntegerField(
        required=False,
        min_value=1,
        help_text=(
            "For md5 mode only: the number of buckets. The pipeline aims for about 200 MB per partition, so start "
            "near the table size divided by 200 MB, counting indexes and TOAST on the source. md5 spreads changed "
            "rows over every bucket, so do not over-partition a small table or one that changes little."
        ),
    )
    partition_size = forms.IntegerField(
        required=False,
        min_value=1,
        help_text="For numerical mode only: rows per bucket of the integer ID, usually 1,000,000 to 10,000,000.",
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")

    def request(self) -> RepartitionRequest:
        data = self.cleaned_data
        keys: list[str] = []
        for part in data["partitioning_keys"].split(","):
            stripped = part.strip()
            if stripped and stripped not in keys:
                keys.append(stripped)
        return RepartitionRequest(
            partition_mode=data["partition_mode"] or None,
            partitioning_keys=tuple(keys),
            partition_format=data["partition_format"] or None,
            partition_count=data["partition_count"],
            partition_size=data["partition_size"],
        )


class TriggerSyncForm(forms.Form):
    reset_pipeline = forms.BooleanField(required=False, label="Reset pipeline (re-sync from scratch)")
    billable = forms.BooleanField(required=False, label="Billable")
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")


def _report(request: HttpRequest, result: StaffActionResult) -> HttpResponse | None:
    if result.ok:
        messages.success(request, result.message)
        return None
    messages.error(request, result.message)
    return HttpResponse(status=400)


def _schema_id(request: HttpRequest) -> UUID:
    schema_id = _uuid_param(request, "schema")
    assert schema_id is not None, "The tool offers schema operations only with a schema in the query"
    return schema_id


def repartition(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(form, RepartitionForm)
    return _report(request, repartition_schema_for_staff(_schema_id(request), form.request()))


def trigger_sync(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    assert form is not None
    result = trigger_schema_sync_for_staff(
        _schema_id(request), billable=form.cleaned_data["billable"], reset_pipeline=form.cleaned_data["reset_pipeline"]
    )
    return _report(request, result)


def pause_schedule(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    return _report(request, pause_schema_schedule_for_staff(_schema_id(request)))


def unpause_schedule(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    return _report(request, unpause_schema_schedule_for_staff(_schema_id(request)))


def recreate_schedule(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    return _report(request, recreate_schema_schedule_for_staff(_schema_id(request)))


@console.register_tool
class WarehouseSourcesTool(ConsoleTool):
    key = TOOL_KEY
    title = "Warehouse sources"
    owner = WAREHOUSE_SOURCES
    group = "Data"
    description = "The schemas of one warehouse source, and the partitioning, schedule and jobs of one schema."

    def page(self, request: HttpRequest) -> Page:
        page_number = request.GET.get("page")
        schema_id = _uuid_param(request, "schema")
        schema = get_schema_for_staff(schema_id) if schema_id is not None else None
        if schema is not None:
            return SchemaPage.build(schema, page_number)
        source_id = _uuid_param(request, "source")
        source = get_source_for_staff(source_id) if source_id is not None else None
        if source is not None:
            return SourcePage.build(source, page_number)
        return Page(
            blocks=(
                Notice(
                    text="Open a source or a schema from its page in Django admin.",
                    link_text="Find a source",
                    href="/admin/warehouse_sources/externaldatasource/",
                ),
            )
        )

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        schema_id = _uuid_param(request, "schema")
        schema = get_schema_for_staff(schema_id) if schema_id is not None else None
        if schema is None:
            return []
        partitioning = schema.partitioning
        # Danger confirms name the whole target, because schema names repeat across sources and teams.
        target = (
            f"schema {schema.name} ({schema.id}) of the {schema.source_type} source {schema.source_id}, "
            f"team {schema.team_name} ({schema.team_id})"
        )
        columns_note = (
            f" Columns: {', '.join(schema.available_columns)}."
            if schema.available_columns
            else " The table has not synced yet."
        )
        operations = [
            ToolOperation(
                key="repartition",
                label="Repartition",
                handler=repartition,
                danger=True,
                form_class=RepartitionForm,
                form_initial={
                    "partition_mode": partitioning.mode or PARTITION_MODE_CHOICES[0],
                    "partitioning_keys": ",".join(partitioning.keys or ()),
                    "partition_format": partitioning.format,
                    "partition_count": partitioning.count,
                    "partition_size": partitioning.size,
                },
                description=(
                    f"Stages the partition settings for {target} and starts a non-billable run. An incremental "
                    "or append-only table is rewritten in storage into the new layout, with no reset and no rows "
                    "pulled again from the source. On a large table that takes hours. A full refresh table, or one "
                    "with a reset pending, is reloaded from the source. The schedule pauses for the run and "
                    "unpauses when it succeeds." + columns_note
                ),
                undo_hint="To undo, repartition again with the settings this page showed before.",
            ),
            ToolOperation(
                key="trigger-sync",
                label="Trigger sync",
                handler=trigger_sync,
                danger=True,
                form_class=TriggerSyncForm,
                description=(
                    f"Starts one run of {target} outside its schedule, for example to retry a failed sync. "
                    "Repartition already starts its own run. A billable run counts toward the customer's bill, and "
                    "a reset syncs the table again from scratch."
                ),
                undo_hint="A started run cannot be undone. Cancel its workflow in Temporal to stop it.",
            ),
            ToolOperation(
                key="pause-schedule",
                label="Pause schedule",
                handler=pause_schedule,
                danger=True,
                form_class=ReasonForm,
                description=f"Stops the scheduled syncs of {target} until the schedule is unpaused.",
                undo_hint="To undo, use Unpause schedule. Remember to unpause when your work is done.",
            ),
            ToolOperation(
                key="unpause-schedule",
                label="Unpause schedule",
                handler=unpause_schedule,
                description=f"Starts the scheduled syncs of {schema.name} again.",
            ),
        ]
        if schema.supports_scheduled_sync:
            operations.append(
                ToolOperation(
                    key="recreate-schedule",
                    label="Recreate schedule",
                    handler=recreate_schedule,
                    description=(
                        "Creates the Temporal schedule when it is missing, for example after an interrupted source "
                        "creation, when pause, unpause or sync fail with workflow not found. An existing schedule is "
                        "updated in place. No run starts. Use Trigger sync for a run, which is non-billable unless "
                        "you choose otherwise."
                    ),
                )
            )
        return operations


for old in ("repartition", "trigger-sync", "pause-schedule", "unpause-schedule", "recreate-schedule"):
    console.register_moved_page(
        old_path=f"admin/warehouse_sources/externaldataschema/<uuid:schema_id>/{old}/",
        title="Schema partitioning and sync",
        url="/admin/console/tools/warehouse-sources/?schema={schema_id}",
    )
