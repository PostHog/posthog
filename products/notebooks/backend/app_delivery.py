from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from rest_framework import serializers

from products.notebooks.backend.app_viewer import native_app_output_ids
from products.notebooks.backend.facade.contracts import AppOutput, AppOutputTab, AppViewGrantResult
from products.notebooks.backend.markdown_conversion import build_markdown_notebook_content
from products.notebooks.backend.models import Notebook, NotebookAppEmbed, NotebookAppRelease, NotebookAppViewGrant
from products.notebooks.backend.sql_v2_state import build_dependency_edges, extract_cells
from products.notebooks.backend.util import _parse_markdown_component_props, iter_markdown_blocks


def revoke_app_view_grants(team_id: int, notebook_id: UUID) -> None:
    NotebookAppViewGrant.objects.for_team(team_id).filter(release__notebook_id=notebook_id).delete()
    NotebookAppEmbed.objects.for_team(team_id).filter(release__notebook_id=notebook_id).delete()


@transaction.atomic
def change_app_view_grant(team_id: int, notebook_id: UUID, email: str, revoke: bool) -> AppViewGrantResult:
    notebook = (
        Notebook.objects.select_for_update(of=("self",))
        .select_related("team")
        .get(pk=notebook_id, team_id=team_id, deleted=False)
    )
    if revoke:
        NotebookAppViewGrant.objects.for_team(notebook.team_id).filter(
            release__notebook=notebook, recipient__email__iexact=email
        ).delete()
        return AppViewGrantResult(url=None, expires_at=None)

    recipient = notebook.team.all_users_with_access().filter(email__iexact=email, is_active=True).first()
    if recipient is None:
        raise serializers.ValidationError({"email": "Choose a member with access to this project."})
    release = (
        NotebookAppRelease.objects.for_team(notebook.team_id)
        .filter(notebook=notebook)
        .only("id")
        .order_by("-revision")
        .first()
    )
    if release is None or notebook.app_published is None:
        raise serializers.ValidationError("Publish the app before granting access.")
    expires_at = timezone.now() + timedelta(days=30)
    grant, _ = NotebookAppViewGrant.objects.for_team(notebook.team_id).update_or_create(
        team=notebook.team, release=release, recipient=recipient, defaults={"expires_at": expires_at}
    )
    return AppViewGrantResult(
        url=reverse("notebook_app_view_grant", args=[notebook.team_id, grant.pk]), expires_at=expires_at
    )


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
        displayed = named or (
            columns[:1] if len(columns) == 1 or viz.get("display") in ("BoldNumber", "Metric") else []
        )
    else:
        displayed = []
    return displayed


def app_output_tabs(
    release: NotebookAppRelease, *, tenant_column: str | None = None, tenant_value: str | None = None
) -> list[AppOutputTab]:
    cells = extract_cells(build_markdown_notebook_content(release.markdown))
    build_dependency_edges(cells)
    allowed = native_app_output_ids(cells)
    sql_cells = {
        cell.node_id: _parse_markdown_component_props(cell.source)
        for cell in iter_markdown_blocks(release.markdown, max_prose_blocks=0)
        if cell.tag_name == "SQLV2" and cell.node_id in allowed
    }
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
        props = sql_cells.get(block.get("node_id"), {})
        result = props.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("columns"), list):
            continue
        columns = result["columns"]
        rows = result.get("first_page") or []
        if not isinstance(rows, list) or not all(isinstance(column, str) for column in columns):
            continue
        if tenant_column is not None:
            if columns.count(tenant_column) != 1:
                raise serializers.ValidationError(
                    {"tenant_column": "Every displayed SQL output must include this tenant column exactly once."}
                )
            idx = columns.index(tenant_column)
            rows = [row for row in rows if isinstance(row, list) and len(row) > idx and row[idx] == tenant_value]
        displayed = [col for col in output_columns(props, columns) if col != tenant_column]
        if displayed:
            indexes = [columns.index(column) for column in displayed]
            tab["blocks"].append(
                {
                    "title": block.get("title") or props.get("title"),
                    "columns": displayed,
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
        .defer("release__sql_rows", "release__variables")
        .first()
    )
    if grant is None or not grant.team.all_users_with_access(user_uuids=[str(grant.recipient.uuid)]).exists():
        return None
    release = grant.release
    tabs = app_output_tabs(release)
    return AppOutput(
        title=release.layout.get("title") or release.title,
        description=release.layout.get("description"),
        revision=release.revision,
        published_at=release.published_at,
        tabs=tabs,
    )
