from dataclasses import asdict
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.core.cache import caches
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from rest_framework import serializers
from rest_framework.exceptions import NotFound, Throttled

from posthog.helpers.email_utils import EmailLookupHandler
from posthog.models import User
from posthog.models.activity_logging.activity_log import Change
from posthog.token_bucket import BucketDecision, Budget, consume

from products.notebooks.backend.activity_logging import log_notebook_activity
from products.notebooks.backend.app_viewer import native_app_output_ids
from products.notebooks.backend.facade.contracts import ActiveAppViewGrant, AppOutput, AppOutputTab, AppViewGrantResult
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppEmbed, NotebookAppRelease, NotebookAppViewGrant
from products.notebooks.backend.sql_v2_state import build_dependency_edges, extract_cells
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


def revoke_published_app_access(team_id: int, notebook_id: UUID) -> None:
    NotebookAppViewGrant.objects.for_team(team_id).filter(release__notebook_id=notebook_id).delete()
    NotebookAppEmbed.objects.for_team(team_id).filter(release__notebook_id=notebook_id).delete()


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
        cell.node_id: _parse_markdown_component_props(cell.source)
        for cell in iter_markdown_blocks(release.markdown, max_prose_blocks=0)
        if cell.tag_name == "SQLV2" and cell.node_id and cell.node_id in allowed
    }


def can_share_chart_rows(props: dict[str, Any]) -> bool:
    if props.get("outputTab") == "results":
        return True
    viz = props.get("vizQuery") or {}
    if not isinstance(viz, dict):
        return False
    chart = viz.get("chartSettings") or {}
    if not isinstance(chart, dict) or chart.get("seriesBreakdownColumn") or chart.get("resultCustomizations"):
        return False
    return viz.get("display") in (
        None,
        "Auto",
        "ActionsTable",
        "BoldNumber",
        "ActionsLineGraph",
        "ActionsAreaGraph",
        "ActionsBar",
        "ActionsUnstackedBar",
        "ActionsStackedBar",
        "ScatterPlot",
    )


def app_output_tabs(release: NotebookAppRelease) -> list[AppOutputTab]:
    sql_cells = displayed_native_sql_cells(release)
    tabs = {tab["id"]: {"title": tab["title"], "blocks": []} for tab in release.layout["tabs"]}
    for block in release.layout["blocks"]:
        tab = tabs.get(block["tab_id"])
        if tab is None:
            continue
        if block["kind"] == "text":
            tab["blocks"].append({"title": block.get("title"), "text": block.get("text")})
            continue
        if block["kind"] != "cell" or block.get("display") == "source":
            continue
        node_id = block.get("node_id")
        props = sql_cells.get(node_id)
        if not props:
            continue
        if not can_share_chart_rows(props):
            tab["blocks"].append(
                {
                    "title": block.get("title"),
                    "text": "Publish this chart as a table or single number to share its values.",
                }
            )
            continue
        result = pinned_sql_result(release, node_id, props.get("runId"))
        if result is None:
            tab["blocks"].append(
                {"title": block.get("title"), "text": "Republish this app to share a verified SQL result."}
            )
            continue
        columns = result["columns"]
        rows = result["first_page"]
        row_count = result.get("row_count")
        partial = isinstance(row_count, int) and len(rows) < row_count
        displayed = output_columns({**props, "result": result}, columns)
        if props.get("outputTab") != "results" and (props.get("vizQuery") or {}).get("display") == "BoldNumber":
            displayed = output_columns({**props, "outputTab": "results"}, columns)[:1]
            rows = rows[:1]
        if displayed:
            indexes = [columns.index(column) for column in displayed]
            tab["blocks"].append(
                {
                    "title": block.get("title") or props.get("title"),
                    "columns": displayed,
                    "partial": partial,
                    "rows": [
                        [row[i] if i < len(row) else None for i in indexes] for row in rows if isinstance(row, list)
                    ],
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
    cache = caches["notebook_app_outputs"]
    cache_key = f"notebook-app-output:v2:{team_id}:{release.pk}"
    cached = cache.get(cache_key)
    if cached is None:
        if not cache.add(cache_key + ":building", True, timeout=20):
            raise Throttled(wait=2, detail="This release is loading. Try again shortly.")
        tabs = app_output_tabs(release)
        cache.set(cache_key, [asdict(tab) for tab in tabs], timeout=300)
    else:
        tabs = [AppOutputTab(**tab) for tab in cached]
    return AppOutput(
        title=release.layout.get("title") or release.title,
        description=release.layout.get("description"),
        revision=release.revision,
        published_at=release.published_at,
        tabs=tabs,
    )
