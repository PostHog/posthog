import json
from contextlib import suppress
from dataclasses import asdict
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from django.core.cache import caches
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from django_redis.cache import RedisCache
from redis.exceptions import LockNotOwnedError
from rest_framework import serializers
from rest_framework.exceptions import NotFound, Throttled

from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change
from posthog.token_bucket import BucketDecision, Budget, consume

from products.notebooks.backend.activity_logging import log_notebook_activity
from products.notebooks.backend.app_release_results import MAX_RELEASE_RESULT_BYTES
from products.notebooks.backend.app_viewer import native_app_output_ids
from products.notebooks.backend.facade.contracts import ActiveAppViewGrant, AppOutput, AppOutputTab, AppViewGrantResult
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppRelease, NotebookAppViewGrant
from products.notebooks.backend.sql_v2_state import (
    build_dependency_edges,
    extract_cells,
    resolve_sql_visualization_props,
)
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks


def active_view_grants(
    team_id: int, notebook_id: UUID, *, offset: int, limit: int
) -> tuple[int, list[ActiveAppViewGrant]]:
    grants = (
        NotebookAppViewGrant.objects.for_team(team_id)
        .filter(release__notebook_id=notebook_id, expires_at__gt=timezone.now())
        .select_related("recipient", "release")
        .only("recipient__uuid", "recipient__email", "release__revision", "expires_at")
        .order_by("recipient__email", "-release__revision", "pk")
    )
    rows = [
        ActiveAppViewGrant(
            recipient_uuid=grant.recipient.uuid,
            email=grant.recipient.email,
            revision=grant.release.revision,
            expires_at=grant.expires_at,
        )
        for grant in grants[offset : offset + limit]
    ]
    return grants.count(), rows


@transaction.atomic
def revoke_published_app_access(team_id: int, notebook_id: UUID, actor: User, was_impersonated: bool) -> None:
    from products.notebooks.backend.app_embeds import revoke_signed_embeds

    notebook = (
        Notebook.objects.select_for_update(of=("self",))
        .select_related("team")
        .only("short_id", "title", "team__organization_id")
        .get(pk=notebook_id, team_id=team_id)
    )
    NotebookAppViewGrant.objects.for_team(team_id).filter(release__notebook_id=notebook_id).delete()
    revoke_signed_embeds(notebook, actor, was_impersonated)


@transaction.atomic
def change_app_view_grant(
    team_id: int,
    notebook_id: UUID,
    revoke: bool,
    actor: User,
    was_impersonated: bool,
    email: str = "",
    revision: int | None = None,
    recipient_uuid: UUID | None = None,
) -> AppViewGrantResult:
    notebook = (
        Notebook.objects.select_for_update(of=("self",))
        .select_related("team")
        .get(pk=notebook_id, team_id=team_id, deleted=False)
    )
    if revoke:
        grants = NotebookAppViewGrant.objects.for_team(team_id).filter(release__notebook=notebook)
        if recipient_uuid:
            grants = grants.filter(recipient__uuid=recipient_uuid)
        else:
            recipients = EmailLookupHandler.users_matching_email(email)
            if recipients.count() > 1:
                raise serializers.ValidationError("Choose the member from the active recipients.")
            grants = grants.filter(recipient__in=recipients)
        removed = list(grants.values_list("recipient__email", "release__revision"))
        if not removed:
            raise NotFound("No app-only access was found for this member.")
        grants.delete()
        log_notebook_activity(
            "updated",
            notebook,
            notebook.team.organization_id,
            team_id,
            actor,
            was_impersonated,
            changes=[
                Change(
                    type="Notebook",
                    action="deleted",
                    field="app_view_grant",
                    before={"recipient": member, "revision": revision},
                )
                for member, revision in removed
            ],
        )
        return AppViewGrantResult(url=None, expires_at=None)

    candidates = list(EmailLookupHandler.users_matching_email(email, User.objects.filter(is_active=True))[:2])
    if len(candidates) != 1 or not notebook.team.all_users_with_access(user_uuids=[str(candidates[0].uuid)]).exists():
        raise serializers.ValidationError({"email": "Choose a member with access to this project."})
    recipient = candidates[0]
    release = (
        NotebookAppRelease.objects.for_team(notebook.team_id)
        .filter(notebook=notebook)
        .only("id", "revision")
        .order_by("-revision")
        .first()
    )
    if release is None or notebook.app_published is None:
        raise serializers.ValidationError("Publish the app before granting access.")
    if release.revision != revision:
        raise serializers.ValidationError({"revision": "Open the latest published release before granting access."})
    expires_at = timezone.now() + timedelta(days=30)
    grant, _ = NotebookAppViewGrant.objects.for_team(notebook.team_id).update_or_create(
        team=notebook.team, release=release, recipient=recipient, defaults={"expires_at": expires_at}
    )
    log_notebook_activity(
        "updated",
        notebook,
        notebook.team.organization_id,
        team_id,
        actor,
        was_impersonated,
        changes=[
            Change(
                type="Notebook",
                action="created",
                field="app_view_grant",
                after={"recipient": recipient.email, "revision": revision},
            )
        ],
    )
    return AppViewGrantResult(
        url=reverse("notebook_app_view_grant", args=[notebook.team_id, grant.pk]), expires_at=expires_at
    )


def automatic_chart_columns(result: dict[str, Any], columns: list[str], display: str | None) -> list[str]:
    types = {
        item[0]: item[1].lower()
        for item in result.get("types") or []
        if isinstance(item, list) and len(item) == 2 and all(isinstance(v, str) for v in item)
    }
    if not types:
        for row in result.get("first_page") or []:
            if isinstance(row, list):
                for name, value in zip(columns, row):
                    if value is not None and name not in types:
                        types[name] = "float" if type(value) in (int, float) else "string"
    numeric = [
        name
        for name in columns
        if not any(kind in types.get(name, "") for kind in ("array", "tuple"))
        and any(kind in types.get(name, "") for kind in ("int", "float", "decimal"))
    ]
    if display in ("BoldNumber", "Metric"):
        return numeric[:1] or columns[:1]
    if display == "ScatterPlot":
        return numeric
    dates = [name for name in columns if "date" in types.get(name, "")]
    x_axis = dates[:1] or [name for name in columns if name not in numeric][:1]
    return x_axis + numeric


def output_columns(props: dict[str, Any], columns: list[str]) -> list[str]:
    viz = props.get("vizQuery") or {}
    displayed = columns
    if props.get("outputTab") == "results" or (isinstance(viz, dict) and viz.get("display") == "ActionsTable"):
        table = viz.get("tableSettings") if isinstance(viz, dict) else None
        selected = table.get("columns") if isinstance(table, dict) else None
        if isinstance(selected, list) and selected:
            displayed = [c["column"] for c in selected if isinstance(c, dict) and c.get("column") in columns]
    elif isinstance(viz, dict):
        settings = viz.get("chartSettings") or {}
        axes = [settings.get("xAxis"), *(settings.get("yAxis") or [])] if isinstance(settings, dict) else []
        named = [axis["column"] for axis in axes if isinstance(axis, dict) and axis.get("column") in columns]
        displayed = named
        if isinstance(settings, dict) and "xAxis" not in settings and "yAxis" not in settings:
            displayed = automatic_chart_columns(props["result"], columns, viz.get("display"))
    else:
        displayed = []
    return displayed


def pinned_sql_result(release: NotebookAppRelease, node_id: str, run_id: str | None) -> dict[str, Any] | None:
    data = release.sql_rows or {}
    schema = data.get(f"schema:{run_id}")
    rows = data.get(run_id)
    if not isinstance(schema, dict) or schema.get("node_id") != node_id or not isinstance(rows, list):
        return None
    columns = schema.get("columns")
    if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
        return None
    return {**schema, "first_page": rows}


def displayed_native_sql_cells(release: NotebookAppRelease) -> dict[str, dict[str, Any]]:
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    build_dependency_edges(cells)
    visible = {
        block["node_id"]
        for block in release.layout["blocks"]
        if block["kind"] == "cell" and block.get("display") != "source"
    }
    allowed = native_app_output_ids(cells) & visible
    return {
        cell.node_id: resolve_sql_visualization_props(_parse_markdown_component_props(cell.source))
        for cell in iter_markdown_blocks(release.markdown, max_prose_blocks=0)
        if cell.tag_name == "SQLV2" and cell.node_id and cell.node_id in allowed
    }


def has_distinct_chart_categories(result: dict[str, Any], settings: dict[str, Any]) -> bool:
    rows = result["first_page"]
    columns = result["columns"]
    if result.get("row_count", len(rows)) != len(rows):
        return False
    if "xAxis" in settings or "yAxis" in settings:
        axis = settings.get("xAxis")
        category = axis.get("column") if isinstance(axis, dict) else None
    else:
        axes = automatic_chart_columns(result, columns, None)
        category = next(iter(axes), None)
    if category == "event" or columns.count(category) != 1:
        return False
    index = columns.index(category)
    seen: set[str | float] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) <= index:
            return False
        value = row[index]
        if not isinstance(value, str) and not (
            "xAxis" in settings and type(value) in (int, float) and abs(value) < 2**53
        ):
            return False
        if value in seen:
            return False
        seen.add(value)
    return True


class SharedOutputLimitExceeded(serializers.ValidationError):
    default_detail = (
        "This app exceeds the shared output limit. Publish smaller results or remove repeated output blocks."
    )


class SharedOutputBudget:
    def __init__(self, *, byte_limit: int) -> None:
        self.bytes_left = byte_limit
        self.cells_left = 50_000

    def count(self, values: list) -> None:
        self.cells_left -= max(1, len(values))
        if self.cells_left < 0:
            raise SharedOutputLimitExceeded()
        self.bytes_left -= 2 + len(values)
        for value in values:
            self.bytes_left -= len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
            if self.bytes_left < 0:
                raise SharedOutputLimitExceeded()

    def project_rows(self, rows: list, indexes: list[int]) -> list[list]:
        output = []
        for row in rows:
            if isinstance(row, list):
                values = [row[index] if index < len(row) else None for index in indexes]
                self.count(values)
                output.append(values)
        return output


def shared_chart_display(props: dict[str, Any], result: dict[str, Any]) -> str | None:
    if props.get("outputTab") == "results":
        return "ActionsTable"
    viz = props.get("vizQuery") or {}
    if not isinstance(viz, dict):
        return None
    display = viz.get("display") or "Auto"
    if display == "Auto":
        columns = result["columns"]
        if len(columns) == 1:
            return "BoldNumber"
        if len(columns) == 2 and len(automatic_chart_columns(result, columns, "ScatterPlot")) == 1:
            display = "ActionsBar"
        else:
            return None
    if display in ("ActionsTable", "BoldNumber"):
        return display
    chart = viz.get("chartSettings") or {}
    if isinstance(chart, dict) and not (chart.get("seriesBreakdownColumn") or chart.get("resultCustomizations")):
        if display == "ScatterPlot":
            return display
        if display in (
            "ActionsLineGraph",
            "ActionsAreaGraph",
            "ActionsBar",
            "ActionsUnstackedBar",
            "ActionsStackedBar",
        ) and has_distinct_chart_categories(result, chart):
            return display
    return None


def app_output_tabs(
    release: NotebookAppRelease,
    *,
    tenant_column: str | None = None,
    tenant_value: str | None = None,
    byte_limit: int | None = None,
) -> list[AppOutputTab]:
    sql_cells = displayed_native_sql_cells(release)
    budget = SharedOutputBudget(byte_limit=MAX_RELEASE_RESULT_BYTES if byte_limit is None else byte_limit)
    budget.count([tab["title"] for tab in release.layout["tabs"]])
    tabs = {tab["id"]: {"title": tab["title"], "blocks": []} for tab in release.layout["tabs"]}
    for block in release.layout["blocks"]:
        tab = tabs.get(block["tab_id"])
        if tab is None:
            continue
        budget.count([block.get("title"), block.get("text")])
        if block["kind"] == "text":
            tab["blocks"].append({"title": block.get("title"), "text": block.get("text")})
            continue
        if block["kind"] != "cell" or block.get("display") == "source":
            continue
        node_id = block.get("node_id")
        props = sql_cells.get(node_id)
        if not props:
            continue
        result = pinned_sql_result(release, node_id, props.get("runId"))
        if result is None:
            if tenant_column is not None:
                raise serializers.ValidationError(
                    "Save and republish the complete SQL results before creating an embed."
                )
            tab["blocks"].append(
                {"title": block.get("title"), "text": "Republish this app to share a verified SQL result."}
            )
            continue
        display = shared_chart_display(props, result)
        if display is None:
            tab["blocks"].append(
                {
                    "title": block.get("title"),
                    "text": "Publish this chart as a table or single number to share its values.",
                }
            )
            continue
        columns = result["columns"]
        rows = result["first_page"]
        row_count = result.get("row_count")
        partial = isinstance(row_count, int) and len(rows) < row_count
        displayed = output_columns({**props, "result": result}, columns)
        if tenant_column is not None:
            if partial:
                raise serializers.ValidationError(
                    "Save and republish the complete SQL results before creating an embed."
                )
            if columns.count(tenant_column) != 1:
                raise serializers.ValidationError(
                    {"tenant_column": "Every displayed SQL output must include this tenant column exactly once."}
                )
            idx = columns.index(tenant_column)
            rows = [row for row in rows if isinstance(row, list) and len(row) > idx and row[idx] == tenant_value]
        if display == "BoldNumber":
            displayed = output_columns({**props, "outputTab": "results"}, columns)[:1]
            rows = rows[:1]
        if tenant_column is not None:
            displayed = [column for column in displayed if column != tenant_column]
        if displayed:
            budget.count(displayed)
            budget.count([props.get("title")])
            indexes = [columns.index(column) for column in displayed]
            tab["blocks"].append(
                {
                    "title": block.get("title") or props.get("title"),
                    "columns": displayed,
                    "partial": partial,
                    "rows": budget.project_rows(rows, indexes),
                }
            )
    return [AppOutputTab(title=tab["title"], blocks=tab["blocks"]) for tab in tabs.values()]


def read_granted_output(team_id: int, recipient_id: int, grant_id: UUID) -> AppOutput | None:
    grant = (
        NotebookAppViewGrant.objects.for_team(team_id)
        .filter(
            pk=grant_id,
            recipient_id=recipient_id,
            expires_at__gt=timezone.now(),
            release__team_id=team_id,
            release__notebook__team_id=team_id,
            release__notebook__deleted=False,
            release__notebook__app_published__isnull=False,
        )
        .select_related("release", "team__organization", "recipient")
        .defer("release__variables", "release__markdown", "release__sql_rows")
        .first()
    )
    if grant is None or not grant.team.all_users_with_access(user_uuids=[str(grant.recipient.uuid)]).exists():
        return None
    release = grant.release
    budget = consume(f"notebooks:app-view:{team_id}:{recipient_id}", Budget(burst=15, per_hour=240))
    if isinstance(budget, BucketDecision) and not budget.allowed:
        raise Throttled(wait=budget.retry_after)
    cache = cast(RedisCache, caches["notebook_app_outputs"])
    cache_key = f"notebook-app-output:v5:{team_id}:{release.pk}"
    cached = cache.get(cache_key)
    if cached is None:
        lock = cache.lock(cache_key + ":building", timeout=20)
        if not lock.acquire(blocking=False):
            raise Throttled(wait=2, detail="This release is loading. Try again shortly.")
        try:
            try:
                tabs = app_output_tabs(release)
            except SharedOutputLimitExceeded:
                tabs = [
                    AppOutputTab(title="Published app", blocks=[{"text": SharedOutputLimitExceeded.default_detail}])
                ]
            cache.set(cache_key, [asdict(tab) for tab in tabs], timeout=300)
        finally:
            with suppress(LockNotOwnedError):
                lock.release()
    else:
        tabs = [AppOutputTab(**tab) for tab in cached]
    return AppOutput(
        title=release.layout.get("title") or release.title,
        description=release.layout.get("description"),
        revision=release.revision,
        published_at=release.published_at,
        tabs=tabs,
    )
