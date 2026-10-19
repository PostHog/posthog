"""Builds a real dashboard from template panels, for the metric names that one team sends."""

from __future__ import annotations

import copy
import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ValidationError

from posthog.schema import (
    MetricsDashboardVariable,
    MetricsDashboardVariableSelection,
    MetricsDashboardVariableSource,
    MetricsHistogramQuery,
    MetricsOtelType,
    MetricsQuery,
    MetricsQueryFilter,
)

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User

from products.dashboards.backend.facade.dashboard_creation import (
    CreatedDashboard,
    DashboardTileSnapshot,
    NewDashboard,
    NewInsightTile,
    NewTextTile,
    TileLayout,
    create_dashboard_with_tiles,
    delete_unlisted_dashboard,
)
from products.metrics.backend.dashboard_import.catalog import MetricCatalog
from products.metrics.backend.dashboard_import.layout import MIN_INSIGHT_HEIGHT, MIN_INSIGHT_WIDTH
from products.metrics.backend.dashboard_import.spec import GRID_COLUMNS, GridLayout
from products.metrics.backend.models import MetricsDashboardTemplate
from products.metrics.backend.suggested_dashboards.matching import query_metric_names
from products.metrics.backend.suggested_dashboards.spec import TemplatePanel
from products.metrics.backend.variables import filter_referenced_names, referenced_names, sql_referenced_names

MAX_TEXT_LENGTH = 4000
# The service is a column, not an attribute key. Metrics queries accept both names.
SERVICE_ATTRIBUTES = frozenset({"service_name", "service.name"})
# The name and attribute tables store hourly buckets, so the bucket that holds the start of the range counts too.
OPTIONS_RANGE = "time_bucket >= toStartOfHour($__from) AND time_bucket < $__to"
_OTEL_TYPES = frozenset(member.value for member in MetricsOtelType)


@frozen
class BuiltTiles:
    tiles: tuple[NewInsightTile | NewTextTile, ...]
    # The titles of the panels that the team cannot fill, because it does not send their metrics.
    dropped: tuple[str, ...]
    dropped_keys: tuple[str, ...] = ()
    # The names of the dashboard variables that the tiles refer to. `create_dashboard` fills them in.
    variable_names: tuple[str, ...] = ()


def _with_team_metric_types(query: dict[str, Any], catalog: MetricCatalog) -> dict[str, Any] | None:
    """A copy of the query with the metric type of each metric as this team sends it, or None when a metric is missing."""
    resolved = copy.deepcopy(query)
    if resolved.get("kind") == "MetricsHistogramQuery":
        entry = catalog.resolve(str(resolved.get("metricName") or ""))
        if entry is None:
            return None
        resolved["metricName"] = entry.name
        if entry.metric_type in _OTEL_TYPES:
            resolved["metricType"] = entry.metric_type
        MetricsHistogramQuery.model_validate(resolved)
        return resolved
    for clause in resolved.get("clauses") or []:
        entry = catalog.resolve(str(clause.get("metricName") or ""))
        if entry is None:
            return None
        if entry.metric_type in _OTEL_TYPES:
            clause["metricType"] = entry.metric_type
        else:
            clause.pop("metricType", None)
    if resolved.get("language") == "promql" and any(
        catalog.resolve(name) is None for name in query_metric_names(resolved)
    ):
        return None
    MetricsQuery.model_validate(resolved)
    return resolved


def _fill_rows(boxes: list[tuple[int, GridLayout]]) -> dict[int, GridLayout]:
    """Spread the boxes of each row across the full width again, after some panels of the row were dropped."""
    rows: dict[int, list[tuple[int, GridLayout]]] = defaultdict(list)
    for index, layout in boxes:
        rows[layout.y].append((index, layout))
    placed: dict[int, GridLayout] = {}
    for top, row in rows.items():
        row.sort(key=lambda item: item[1].x)
        total = sum(layout.w for _, layout in row)
        bottom = top + max(layout.h for _, layout in row)
        # A tile of another row beside this one, such as a tall tile, keeps its columns.
        crossed = any(layout.y != top and layout.y < bottom and layout.y + layout.h > top for _, layout in boxes)
        if total >= GRID_COLUMNS or not total or crossed:
            placed.update(dict(row))
            continue
        widths = [max(MIN_INSIGHT_WIDTH, layout.w * GRID_COLUMNS // total) for _, layout in row]
        widths[-1] += GRID_COLUMNS - sum(widths)
        cursor = 0
        for (index, layout), width in zip(row, widths):
            placed[index] = GridLayout(x=cursor, y=layout.y, w=width, h=layout.h)
            cursor += width
    return placed


def build_tiles(panels: Sequence[TemplatePanel], catalog: MetricCatalog, *, refill: bool = True) -> BuiltTiles:
    """The tiles of the panels that the team can fill. With `refill`, the rows of dropped panels spread out again."""
    kept: list[tuple[TemplatePanel, dict[str, Any] | None]] = []
    dropped: list[TemplatePanel] = []
    for panel in panels:
        if panel.query is None:
            if panel.text:
                kept.append((panel, None))
            continue
        try:
            query = _with_team_metric_types(panel.query, catalog)
        except ValidationError:
            query = None
        if query is None:
            dropped.append(panel)
        else:
            kept.append((panel, query))
    layouts = _fill_rows([(index, panel.layout) for index, (panel, _) in enumerate(kept)]) if dropped and refill else {}
    tiles: list[NewInsightTile | NewTextTile] = []
    for index, (panel, query) in enumerate(kept):
        layout = layouts.get(index, panel.layout).clamped(
            min_w=1 if query is None else MIN_INSIGHT_WIDTH, min_h=1 if query is None else MIN_INSIGHT_HEIGHT
        )
        box = TileLayout(x=layout.x, y=layout.y, w=layout.w, h=layout.h)
        if query is None:
            tiles.append(NewTextTile(body=(panel.text or "")[:MAX_TEXT_LENGTH], layout=box))
        else:
            tiles.append(NewInsightTile(name=panel.title, description=panel.description, query=query, layout=box))
    return BuiltTiles(
        tiles=tuple(tiles),
        dropped=tuple(panel.title for panel in dropped),
        dropped_keys=tuple(panel.key for panel in dropped),
    )


def attribute_variable(*, name: str, label: str, attribute: str, multi: bool = False) -> dict[str, Any]:
    """A dashboard variable whose options are the values of one attribute in the team that opens the dashboard.

    It selects All, so its filters match everything until the user picks a value.
    """
    if attribute in SERVICE_ATTRIBUTES:
        # The name table has far fewer rows than the attribute table, and holds every service too.
        query = f"SELECT DISTINCT service_name FROM posthog.metric_names WHERE {OPTIONS_RANGE}"
    else:
        key = attribute.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            "SELECT DISTINCT attribute_value FROM posthog.metric_attributes "
            f"WHERE attribute_key = '{key}' AND {OPTIONS_RANGE}"
        )
    return MetricsDashboardVariable(
        name=name,
        label=label or None,
        source=MetricsDashboardVariableSource.SQL,
        query=query,
        multi=multi,
        includeAll=True,
        current=MetricsDashboardVariableSelection(values=[], all=True),
    ).model_dump(mode="json", exclude_none=True)


def _query_references(query: dict[str, Any]) -> list[str]:
    filters = [*(query.get("filters") or []), *(query.get("metricFilters") or [])]
    for clause in query.get("clauses") or []:
        filters.extend(clause.get("filters") or [])
    return [
        *filter_referenced_names(MetricsQueryFilter.model_validate(item) for item in filters),
        *referenced_names(query.get("promql")),
        *sql_referenced_names(query.get("sql")),
    ]


def referenced_variables(
    queries: Iterable[dict[str, Any]], variables: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The variables that the queries refer to, and the variables that their options queries refer to, in order."""
    by_name = {str(variable.get("name")): variable for variable in variables}
    pending = [name for query in queries for name in _query_references(query)]
    needed: set[str] = set()
    while pending:
        name = pending.pop()
        if name in needed or name not in by_name:
            continue
        needed.add(name)
        definition = by_name[name]
        options_query = definition.get("query")
        if definition.get("source") == MetricsDashboardVariableSource.SQL:
            pending.extend(sql_referenced_names(options_query))
        else:
            pending.extend(referenced_names(options_query))
    return [variable for variable in variables if variable.get("name") in needed]


def create_dashboard(
    *,
    team: Team,
    user: User,
    name: str,
    description: str,
    panels: Sequence[TemplatePanel],
    catalog: MetricCatalog,
    idempotency_key: str,
    unlisted: bool = False,
    refill: bool = True,
    variables: Sequence[dict[str, Any]] = (),
) -> tuple[CreatedDashboard | None, BuiltTiles]:
    """Create the dashboard as the user. Returns no dashboard when no panel has data in this team.

    The dashboard gets only the variables that its tiles refer to.
    """
    built = build_tiles(panels, catalog, refill=refill)
    if not any(isinstance(tile, NewInsightTile) for tile in built.tiles):
        return None, built
    kept_variables = referenced_variables(
        (tile.query for tile in built.tiles if isinstance(tile, NewInsightTile)), variables
    )
    built = dataclasses.replace(built, variable_names=tuple(str(variable["name"]) for variable in kept_variables))
    created = create_dashboard_with_tiles(
        team_id=team.id,
        user_id=user.id,
        dashboard=NewDashboard(
            name=name,
            description=description,
            tiles=built.tiles,
            idempotency_key=idempotency_key,
            unlisted=unlisted,
            filters={"metricVariables": kept_variables} if kept_variables else None,
        ),
    )
    return created, built


def panels_from_tiles(snapshots: Sequence[DashboardTileSnapshot]) -> list[TemplatePanel]:
    """Template panels from the tiles of a dashboard that a person or PostHog AI changed. Unknown tiles are left out."""
    panels: list[TemplatePanel] = []
    # A tile that PostHog AI adds has no saved box yet. It goes below the others, two to a row.
    bottom = max((snapshot.layout.y + snapshot.layout.h for snapshot in snapshots if snapshot.layout), default=0)
    unplaced = 0
    for index, snapshot in enumerate(snapshots):
        layout = snapshot.layout
        if layout is None:
            layout = TileLayout(x=(unplaced % 2) * 6, y=bottom + (unplaced // 2) * 4, w=6, h=4)
            unplaced += 1
        box = GridLayout(x=layout.x, y=layout.y, w=layout.w, h=layout.h)
        if snapshot.query is not None:
            if snapshot.query.get("kind") not in ("MetricsQuery", "MetricsHistogramQuery"):
                continue
            query = copy.deepcopy(snapshot.query)
            # The team's own metric types fill in again when a team applies the template.
            for clause in query.get("clauses") or []:
                clause.pop("metricType", None)
            query.pop("metricType", None)
            query.pop("dateRange", None)
            panels.append(
                TemplatePanel(
                    key=f"p{index + 1}",
                    title=snapshot.name or "Untitled panel",
                    description=snapshot.description,
                    query=query,
                    layout=box,
                )
            )
        elif snapshot.body:
            panels.append(TemplatePanel(key=f"p{index + 1}", title="", text=snapshot.body, layout=box))
    return panels


def drop_preview(template: MetricsDashboardTemplate) -> None:
    """Delete the template's preview dashboard and forget it. The caller saves the template."""
    if template.preview_team_id and template.preview_dashboard_id:
        delete_unlisted_dashboard(team_id=template.preview_team_id, dashboard_id=template.preview_dashboard_id)
    template.preview_team_id = None
    template.preview_dashboard_id = None
    template.preview_unbuilt_keys = []


def acting_user(team: Team) -> User | None:
    """The user that a background job acts as, to build and render a preview: the longest-standing admin of the organization."""
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            level__gte=OrganizationMembership.Level.ADMIN,
            user__is_active=True,
        )
        .select_related("user")
        .order_by("joined_at")
        .first()
    )
    return membership.user if membership else None
