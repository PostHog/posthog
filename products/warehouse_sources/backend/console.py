import json
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlencode
from uuid import UUID

from django import forms
from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse, QueryDict
from django.urls import reverse

from posthog.admin.console.panels import Owner, ReasonForm, Tone
from posthog.admin.console.registry import console
from posthog.admin.console.tools import (
    Cell,
    ConsoleTool,
    FieldGroup,
    Filters,
    Notice,
    Page,
    Paging,
    Row,
    Stat,
    Stats,
    Table,
    ToolOperation,
)
from posthog.utils import pluralize

from products.warehouse_sources.backend.facade.contracts import (
    AutoDisabledErrorGroup,
    AutoDisabledSchemaFilter,
    AutoDisabledSchemaRow,
    AutoDisabledSchemasSummary,
    RepartitionRequest,
    SchemaReenableResult,
    SchemaReenableTarget,
    StaffActionResult,
    StaffSchemaSummary,
    StaffSourceSummary,
)
from products.warehouse_sources.backend.facade.staff import (
    DAYS_CHOICES,
    DEFAULT_DAYS,
    MAX_REENABLE_PER_RUN,
    PARTITION_FORMAT_CHOICES,
    PARTITION_MODE_CHOICES,
    REENABLE_TIME_BUDGET_SECONDS,
    get_schema_for_staff,
    get_source_for_staff,
    list_auto_disabled_schemas_for_staff,
    list_schema_jobs_for_staff,
    list_source_schemas_for_staff,
    pause_schema_schedule_for_staff,
    recreate_schema_schedule_for_staff,
    reenable_schemas_for_staff,
    repartition_schema_for_staff,
    select_auto_disabled_schemas_for_staff,
    summarize_auto_disabled_schemas_for_staff,
    trigger_schema_sync_for_staff,
    unpause_schema_schedule_for_staff,
)

WAREHOUSE_SOURCES = Owner(name="Warehouse sources", crest="warehouse-sources")
TOOL_KEY = "warehouse-sources"
REENABLE_TOOL_KEY = "warehouse-sources-reenable"

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
# Errors without digits, such as one per missing table name, can make a group each. The page stays readable.
MAX_GROUPS_SHOWN = 50


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


def _reenable_url(**params: str) -> str:
    return f"{reverse('admin_console_tool', kwargs={'tool_key': REENABLE_TOOL_KEY})}?{urlencode(params)}"


def _team_url(team_id: int) -> str:
    return reverse("admin_console_team", kwargs={"pk": team_id})


def _temporal_url(path: str) -> str:
    return f"{settings.TEMPORAL_UI_HOST}/namespaces/{settings.TEMPORAL_NAMESPACE}/{path}"


def _uuid_param(request: HttpRequest, name: str) -> UUID | None:
    try:
        return UUID(request.GET.get(name, "").strip())
    except ValueError:
        return None


def _paging(
    number: int,
    num_pages: int,
    count: int,
    noun: str,
    params: dict[str, str],
    url: Callable[..., str] = _tool_url,
) -> Paging:
    return Paging(
        number=number,
        num_pages=num_pages,
        summary=f"{count} {noun} in total",
        previous_url=url(**params, page=str(number - 1)) if number > 1 else None,
        next_url=url(**params, page=str(number + 1)) if number < num_pages else None,
    )


def _is_auto_disabled(schema: StaffSchemaSummary) -> bool:
    return schema.auto_disabled_at is not None and not schema.should_sync and not schema.deleted


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
        return table, _paging(page.number, page.num_pages, page.count, "jobs", {"schema": str(schema.id)})

    @staticmethod
    def auto_disabled(schema: StaffSchemaSummary) -> tuple[Notice, ...]:
        if not _is_auto_disabled(schema):
            return ()
        return (
            Notice(
                text=f"PostHog stopped syncing this schema at {_time(schema.auto_disabled_at)} UTC, after an error "
                "that retrying would not fix. Fix the cause before you re-enable syncing, or the next sync stops it "
                "again.",
                tone=Tone.WARNING,
                link_text="Other stopped schemas of this source type",
                href=_reenable_url(days=str(max(DAYS_CHOICES)), source_type=schema.source_type),
            ),
        )

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
                *cls.auto_disabled(schema),
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
                _paging(page.number, page.num_pages, page.count, "schemas", {"source": str(source.id)}),
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


def reenable_schema(request: HttpRequest, form: forms.Form | None) -> HttpResponse | None:
    schema = get_schema_for_staff(_schema_id(request))
    assert schema is not None, "The tool offers this operation only for an existing schema"
    result = reenable_schemas_for_staff(
        [SchemaReenableTarget(schema_id=schema.id, team_id=schema.team_id, auto_disabled_at=schema.auto_disabled_at)]
    )
    if result.reenabled:
        return _report(request, StaffActionResult(ok=True, message="Syncing is on again. The schedule is unpaused."))
    if result.failed:
        message = "Couldn't re-enable syncing, so syncing stays off. Check the schedule in Temporal, then try again."
    else:
        message = "The schema changed since this page loaded. Reload the page and check its state."
    return _report(request, StaffActionResult(ok=False, message=message))


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
        if _is_auto_disabled(schema):
            operations.insert(
                0,
                ToolOperation(
                    key="reenable-syncing",
                    label="Re-enable syncing",
                    handler=reenable_schema,
                    description=(
                        f"Turns syncing back on for {schema.name}, which PostHog stopped after an error. The "
                        "schedule is unpaused and the failure streak resets, so the next sync runs on the normal "
                        "cadence."
                    ),
                ),
            )
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


FILTER_PARAMS = ("days", "source_type", "error", "team")
SCHEMA_COLUMNS = ("Schema", "Team", "Source type", "Stopped at (UTC)", "Latest error")


class AutoDisabledFilterForm(forms.Form):
    days = forms.TypedChoiceField(
        label="Stopped in the last",
        choices=[(str(days), pluralize(days, "day")) for days in DAYS_CHOICES],
        coerce=int,
        # A link may send `days=` with no value, which means the default.
        empty_value=None,
        required=False,
        initial=str(DEFAULT_DAYS),
    )
    source_type = forms.CharField(
        label="Source type", required=False, help_text="The exact source type, for example Postgres or Stripe."
    )
    error = forms.CharField(label="Error contains", required=False, help_text="Matches any letter case.")
    team = forms.IntegerField(label="Team ID", required=False, min_value=1)

    def selection(self) -> AutoDisabledSchemaFilter:
        data = self.cleaned_data
        return AutoDisabledSchemaFilter(
            days=data["days"] or DEFAULT_DAYS,
            source_type=data["source_type"] or None,
            error=data["error"] or None,
            team_id=data["team"],
        )


def _filter_params(selection: AutoDisabledSchemaFilter) -> dict[str, str]:
    # The same names are the contract for links into this tool from outside the console.
    params = {"days": str(selection.days)}
    if selection.source_type:
        params["source_type"] = selection.source_type
    if selection.error:
        params["error"] = selection.error
    if selection.team_id is not None:
        params["team"] = str(selection.team_id)
    return params


def _schema_link(schema_id: UUID, text: str) -> Cell:
    return Cell(text=text, href=_tool_url(schema=str(schema_id)))


def _schema_rows(rows: tuple[AutoDisabledSchemaRow, ...]) -> tuple[Row, ...]:
    return tuple(
        Row(
            cells=(
                _schema_link(row.id, row.name),
                Cell(text=str(row.team_id), href=_team_url(row.team_id)),
                Cell(text=row.source_type),
                Cell(text=_time(row.auto_disabled_at)),
                Cell(text=_truncate(row.latest_error, ERROR_PREVIEW_LENGTH))
                if row.latest_error
                else Cell(text="No error recorded", muted=True),
            )
        )
        for row in rows
    )


class ReenableToolPage:
    INTRO = (
        "PostHog stops syncing a schema when a sync fails with an error that retrying would not fix. This tool "
        "lists those schemas, and not the schemas a customer turned off. Fix the cause before you re-enable a "
        "group, or the next sync stops the schemas again."
    )

    @staticmethod
    def filters_form(request: HttpRequest) -> AutoDisabledFilterForm:
        if any(name in request.GET for name in FILTER_PARAMS):
            return AutoDisabledFilterForm(request.GET)
        return AutoDisabledFilterForm()

    @staticmethod
    def groups(summary: AutoDisabledSchemasSummary, selection: AutoDisabledSchemaFilter) -> Table:
        def row(group: AutoDisabledErrorGroup) -> Row:
            by_type = AutoDisabledSchemaFilter(
                days=selection.days, source_type=group.source_type, team_id=selection.team_id
            )
            by_error = AutoDisabledSchemaFilter(
                days=selection.days, source_type=group.source_type, error=group.error, team_id=selection.team_id
            )
            return Row(
                cells=(
                    Cell(text=group.source_type, href=_reenable_url(**_filter_params(by_type))),
                    Cell(text=group.error, href=_reenable_url(**_filter_params(by_error)))
                    if group.error
                    else Cell(text="No error recorded", muted=True),
                    Cell(text=str(group.count)),
                    Cell(text=_time(group.newest_at)),
                    Cell(text=_time(group.oldest_at)),
                )
            )

        return Table(
            title="By source type and error",
            columns=("Source type", "Error starts with", "Schemas", "Newest (UTC)", "Oldest (UTC)"),
            rows=tuple(row(group) for group in summary.groups[:MAX_GROUPS_SHOWN]),
            numeric_columns=(2,),
            empty_text="No auto-disabled schemas match these filters.",
        )

    @classmethod
    def build(cls, request: HttpRequest) -> Page:
        form = cls.filters_form(request)
        filters = Filters(
            form=form,
            groups=(FieldGroup(title="Filters", field_names=FILTER_PARAMS),),
            submit_label="Show schemas",
        )
        if form.is_bound and not form.is_valid():
            return Page(
                blocks=(
                    Notice(text=cls.INTRO),
                    filters,
                    Notice(text="Fix the filters to see the matching schemas.", tone=Tone.WARNING),
                )
            )
        selection = form.selection() if form.is_bound else AutoDisabledSchemaFilter(days=DEFAULT_DAYS)
        summary = summarize_auto_disabled_schemas_for_staff(selection)
        page = list_auto_disabled_schemas_for_staff(selection, request.GET.get("page"))
        blocks: list[Notice | Filters | Stats | Table | Paging] = [
            Notice(text=cls.INTRO),
            filters,
            Stats(
                items=(
                    Stat(label="Auto-disabled schemas", value=str(summary.total)),
                    Stat(label="Teams", value=str(summary.team_count)),
                    Stat(label="Sources", value=str(summary.source_count)),
                )
            ),
            cls.groups(summary, selection),
        ]
        if len(summary.groups) > MAX_GROUPS_SHOWN:
            blocks.append(
                Notice(
                    text=f"The table shows the {MAX_GROUPS_SHOWN} largest of {len(summary.groups)} groups. "
                    "Filter by source type or error to see the others."
                )
            )
        if summary.grouped_count < summary.total:
            blocks.append(Notice(text=f"The groups count only the newest {summary.grouped_count} schemas."))
        blocks += [
            Table(
                title="Schemas",
                columns=SCHEMA_COLUMNS,
                rows=_schema_rows(page.rows),
                empty_text="No auto-disabled schemas match these filters.",
            ),
            _paging(page.number, page.num_pages, page.count, "schemas", _filter_params(selection), _reenable_url),
        ]
        return Page(blocks=tuple(blocks))


class ReenableSchemasForm(AutoDisabledFilterForm):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="Goes into the audit log.")
    # The preview fills this with the schemas it showed and the time each one stopped. The signed confirm token
    # carries it, so the confirm step acts on exactly those schemas and skips any that changed since.
    previewed = forms.CharField(widget=forms.HiddenInput, required=False)

    def clean_previewed(self) -> tuple[SchemaReenableTarget, ...]:
        raw = self.cleaned_data["previewed"]
        if not raw:
            return ()
        try:
            targets = tuple(
                SchemaReenableTarget(
                    schema_id=UUID(item["schema_id"]),
                    team_id=int(item["team_id"]),
                    auto_disabled_at=datetime.fromisoformat(item["auto_disabled_at"]),
                )
                for item in json.loads(raw)
            )
        except (TypeError, KeyError, ValueError):
            raise forms.ValidationError("The previewed schemas could not be read. Preview them again.")
        if len(targets) > MAX_REENABLE_PER_RUN:
            raise forms.ValidationError(f"One run re-enables {MAX_REENABLE_PER_RUN} schemas or fewer.")
        return targets

    def record_preview(self, rows: tuple[AutoDisabledSchemaRow, ...]) -> None:
        assert isinstance(self.data, QueryDict)
        data = self.data.copy()
        data["previewed"] = json.dumps(
            [
                {"schema_id": str(row.id), "team_id": row.team_id, "auto_disabled_at": row.auto_disabled_at.isoformat()}
                for row in rows
            ]
        )
        self.data = data


def preview_reenable(request: HttpRequest, form: forms.Form) -> Page:
    assert isinstance(form, ReenableSchemasForm)
    selection = select_auto_disabled_schemas_for_staff(form.selection())
    if not selection.rows:
        form.add_error(None, "No auto-disabled schemas match these filters. Change the filters and try again.")
        return Page(blocks=())
    form.record_preview(selection.rows)
    text = (
        f"Turns syncing back on for {pluralize(len(selection.rows), 'schema')}. Their schedules are unpaused and "
        "their failure streaks reset. A schema that changes before you confirm is skipped."
    )
    remaining = selection.total - len(selection.rows)
    if remaining:
        text += f" One run takes the newest {MAX_REENABLE_PER_RUN}. Run it again for the rest ({remaining} left)."
    return Page(blocks=(Notice(text=text), Table(columns=SCHEMA_COLUMNS, rows=_schema_rows(selection.rows))))


def _result_page(result: SchemaReenableResult, selection: AutoDisabledSchemaFilter) -> Page:
    blocks: list[Notice | Stats | Table] = [
        Stats(
            items=(
                Stat(label="Re-enabled", value=str(len(result.reenabled)), tone=Tone.SUCCESS),
                Stat(label="Skipped", value=str(len(result.skipped))),
                Stat(label="Failed", value=str(len(result.failed)), tone=Tone.DESTRUCTIVE if result.failed else None),
                Stat(
                    label="Not attempted",
                    value=str(len(result.not_attempted)),
                    tone=Tone.WARNING if result.not_attempted else None,
                ),
            )
        )
    ]
    if result.not_attempted:
        blocks.append(
            Notice(
                text=(
                    f"The run reached its {REENABLE_TIME_BUDGET_SECONDS} second limit and stopped starting schemas. "
                    "The schemas it did not start are unchanged. Run the operation again for them."
                ),
                tone=Tone.WARNING,
            )
        )
    if result.skipped:
        blocks.append(
            Notice(text="Skipped schemas were turned on, deleted or stopped again after the preview. Nothing changed.")
        )
    if result.failed:
        blocks += [
            Notice(
                text=(
                    "Failed schemas keep syncing off. Open each one to check its schedule in Temporal, then try again."
                ),
                tone=Tone.DESTRUCTIVE,
            ),
            Table(
                title="Failed schemas",
                columns=("Schema ID",),
                rows=tuple(Row(cells=(_schema_link(schema_id, str(schema_id)),)) for schema_id in result.failed),
            ),
        ]
    remaining = select_auto_disabled_schemas_for_staff(selection).total
    if remaining:
        blocks.append(
            Notice(
                text=f"Schemas that still match these filters: {remaining}.",
                link_text="Review the next batch",
                href=_reenable_url(**_filter_params(selection)),
            )
        )
    return Page(blocks=tuple(blocks))


def reenable_schemas(request: HttpRequest, form: forms.Form | None) -> HttpResponse | Page | None:
    assert isinstance(form, ReenableSchemasForm)
    targets = form.cleaned_data["previewed"]
    if not targets:
        messages.error(request, "Nothing was previewed. Preview the schemas again before you re-enable them.")
        return HttpResponse(status=400)
    result = reenable_schemas_for_staff(targets, time_budget_seconds=REENABLE_TIME_BUDGET_SECONDS)
    return _result_page(result, form.selection())


@console.register_tool
class ReenableAutoDisabledSchemasTool(ConsoleTool):
    key = REENABLE_TOOL_KEY
    title = "Re-enable auto-disabled schemas"
    owner = WAREHOUSE_SOURCES
    group = "Data"
    description = (
        "Schemas PostHog stopped syncing after an error that retrying would not fix. Re-enables them after a preview."
    )

    def page(self, request: HttpRequest) -> Page:
        return ReenableToolPage.build(request)

    def operations(self, request: HttpRequest) -> list[ToolOperation]:
        initial: dict[str, object] = {"days": str(DEFAULT_DAYS)}
        initial.update({name: request.GET[name] for name in FILTER_PARAMS if request.GET.get(name)})
        return [
            ToolOperation(
                key="reenable",
                label="Re-enable schemas",
                handler=reenable_schemas,
                preview=preview_reenable,
                danger=True,
                form_class=ReenableSchemasForm,
                form_initial=initial,
                description=(
                    "Turns syncing back on for the auto-disabled schemas that match the filters, the newest "
                    f"{MAX_REENABLE_PER_RUN} per run. Their schedules are unpaused, so the customer's syncs start "
                    "again on the normal cadence. You see each schema before anything changes. A run stops starting "
                    f"new schemas after {REENABLE_TIME_BUDGET_SECONDS} seconds."
                ),
                undo_hint=(
                    "To undo for a schema, open it in the Warehouse sources tool and use Pause schedule, or ask the "
                    "customer to turn syncing off in the app."
                ),
                pending_label="Re-enabling schemas",
            )
        ]
