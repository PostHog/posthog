import re
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

APP_OUTPUT_VERSION = 7
MAX_SHARED_CHART_SERIES = 200
APP_VIEW_RECIPIENT_BUDGET = Budget(burst=60, per_hour=960)
APP_VIEW_PROJECT_RECIPIENT_BUDGET = Budget(burst=15, per_hour=240)


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
def revoke_published_app_access(team_id: int, notebook_id: UUID, actor: User | None, was_impersonated: bool) -> None:
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


def table_columns(viz: dict[str, Any], columns: list[str]) -> list[str]:
    table = viz.get("tableSettings")
    selected = table.get("columns") if isinstance(table, dict) else None
    if isinstance(selected, list) and selected:
        return [c["column"] for c in selected if isinstance(c, dict) and c.get("column") in columns]
    return columns


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


def plain_chart_axis(axis: Any) -> str | None:
    if not isinstance(axis, dict) or axis.keys() - {"column", "settings"}:
        return None
    if axis.get("settings") not in (None, {}, {"formatting": {"prefix": "", "suffix": ""}}):
        return None
    name = axis.get("column")
    return name if isinstance(name, str) and name else None


def pinned_chart_types(result: dict[str, Any]) -> dict[str, str]:
    columns = result["columns"]
    types = result.get("types")
    if not isinstance(types, list) or len(types) != len(columns) or len(set(columns)) != len(columns):
        return {}
    resolved = {}
    for column, typed in zip(columns, types):
        if not isinstance(typed, list) or len(typed) != 2 or typed[0] != column or not isinstance(typed[1], str):
            return {}
        resolved[column] = typed[1]
    return resolved


def verified_chart_columns(result: dict[str, Any], chart: dict[str, Any]) -> list[str]:
    types = pinned_chart_types(result)
    numeric = {name for name, kind in types.items() if re.fullmatch(r"(?:U?Int(?:8|16|32|64)|Float(?:32|64))", kind)}
    categories = {name for name, kind in types.items() if kind == "String" and name != "event"}
    if chart.keys() - {"xAxis", "yAxis"}:
        return []
    if not chart:
        if len(types) != 2 or len(categories) != 1 or len(numeric) != 1:
            return []
        return [*categories, *numeric]
    x_axis = plain_chart_axis(chart.get("xAxis"))
    y_axes = chart.get("yAxis")
    if (
        x_axis is None
        or x_axis not in categories
        or not isinstance(y_axes, list)
        or not 0 < len(y_axes) <= MAX_SHARED_CHART_SERIES
    ):
        return []
    series: list[str] = []
    for axis in y_axes:
        name = plain_chart_axis(axis)
        if name is None or name not in numeric or name in series:
            return []
        series.append(name)
    return [x_axis, *series]


def chart_rows_match_axes(result: dict[str, Any], axes: list[str]) -> bool:
    rows = result["first_page"]
    if not axes or result.get("row_count") != len(rows):
        return False
    category, *series = [result["columns"].index(name) for name in axes]
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != len(result["columns"]):
            return False
        value = row[category]
        if not isinstance(value, str) or not value or value in seen:
            return False
        if any(type(row[index]) not in (int, float) or not abs(row[index]) < 2**53 for index in series):
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


def shared_display_columns(props: dict[str, Any], result: dict[str, Any]) -> tuple[str, list[str]] | None:
    viz = props.get("vizQuery", {})
    columns = result["columns"]
    if props.get("outputTab") == "results":
        return "ActionsTable", table_columns(viz if isinstance(viz, dict) else {}, columns)
    if not isinstance(viz, dict):
        return None
    display = viz.get("display") or "Auto"
    if display == "ActionsTable":
        return display, table_columns(viz, columns)
    if display == "BoldNumber" or (display == "Auto" and len(columns) == 1):
        return "BoldNumber", table_columns(viz, columns)[:1]
    if display == "Auto" and len(columns) != 2:
        return None
    if display not in (
        "Auto",
        "ActionsLineGraph",
        "ActionsAreaGraph",
        "ActionsBar",
        "ActionsUnstackedBar",
        "ActionsStackedBar",
    ):
        return None
    chart = viz.get("chartSettings", {})
    if not isinstance(chart, dict) or viz.get("tableSettings"):
        return None
    axes = verified_chart_columns(result, chart)
    return (display, axes) if chart_rows_match_axes(result, axes) else None


def projected_result_block(
    result: dict[str, Any],
    projection: tuple[str, list[str]],
    title: str | None,
    budget: SharedOutputBudget,
    tenant_column: str | None,
    tenant_value: str | None,
) -> dict[str, Any] | None:
    columns = result["columns"]
    rows = result["first_page"]
    row_count = result.get("row_count")
    partial = isinstance(row_count, int) and len(rows) < row_count
    display, displayed = projection
    if tenant_column is not None:
        if partial:
            raise serializers.ValidationError("Save and republish the complete SQL results before creating an embed.")
        if columns.count(tenant_column) != 1:
            raise serializers.ValidationError(
                {"tenant_column": "Every displayed SQL output must include this tenant column exactly once."}
            )
        idx = columns.index(tenant_column)
        rows = [row for row in rows if isinstance(row, list) and len(row) > idx and row[idx] == tenant_value]
    if display == "BoldNumber":
        rows = rows[:1]
    if tenant_column is not None:
        displayed = [column for column in displayed if column != tenant_column]
    if not displayed:
        return None
    budget.count(displayed)
    budget.count([title])
    indexes = [columns.index(column) for column in displayed]
    return {"title": title, "columns": displayed, "partial": partial, "rows": budget.project_rows(rows, indexes)}


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
        projection = shared_display_columns(props, result)
        if projection is None:
            tab["blocks"].append(
                {
                    "title": block.get("title"),
                    "text": "Publish this chart as a table or single number to share its values.",
                }
            )
            continue
        output = projected_result_block(
            result, projection, block.get("title") or props.get("title"), budget, tenant_column, tenant_value
        )
        if output is not None:
            tab["blocks"].append(output)
    return [AppOutputTab(title=tab["title"], blocks=tab["blocks"]) for tab in tabs.values()]


def check_app_view_budget(recipient_id: int, *, team_id: int | None = None) -> None:
    if team_id is None:
        decision = consume(f"notebooks:app-view-lookup:{recipient_id}", APP_VIEW_RECIPIENT_BUDGET)
    else:
        decision = consume(f"notebooks:app-view:{team_id}:{recipient_id}", APP_VIEW_PROJECT_RECIPIENT_BUDGET)
    if isinstance(decision, BucketDecision) and not decision.allowed:
        raise Throttled(wait=decision.retry_after)


def read_granted_output(team_id: int, recipient_id: int, grant_id: UUID) -> AppOutput | None:
    check_app_view_budget(recipient_id, team_id=team_id)
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
    cache = cast(RedisCache, caches["notebook_app_outputs"])
    cache_key = f"notebook-app-output:v{APP_OUTPUT_VERSION}:{team_id}:{release.pk}"
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
