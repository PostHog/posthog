"""Backfill for notebook query nodes still holding legacy snake_case insight filters.

Notebooks written before the query schema moved to camelCase store keys like
`trendsFilter.show_legend`, `funnelsFilter.funnel_viz_type`, and a `breakdown` object on the
query itself. Nothing writes those shapes any more. They keep working only because the browser
rewrites them on every load: `convertInsightQueriesToNewSchema` in
`frontend/src/scenes/notebooks/Notebook/migrations/migrate.ts` calls the `filtersToQueryNode`
sub-converters before the notebook renders.

This module rewrites the stored content instead, so those sub-converters can be deleted. The
mapping mirrors the browser converters, because what they produce is what these notebooks
already render as today.

Reach and boundaries:

* Only top-level nodes of `content.content` are visited, which is all `migrate` ever mapped.
  A legacy shape nested deeper was never converted, so rewriting it here would change what a
  reader sees rather than preserve it.
* A node's `query` is rewritten whether it is stored as an object or as a JSON string, because
  both shapes hold legacy filters in production. A string is written back as a string, so this
  backfill changes filter keys and nothing else.
* `InsightVizNode.source` is the only place filters are read from, matching the browser
  converter and the fleet-wide census.
* An unparseable JSON string is left untouched and counted. The browser replaces such a query
  with an empty data table, which would discard whatever the string holds.

Legacy funnel `exclusions`, which carry a `type` instead of a `kind`, are converted in the same
pass as the funnel filter keys. They have to be, because the browser reaches them through an
`else if`: while a funnel filter still holds legacy keys, `funnelsFilterToQuery` converts the
exclusions on its way past, and `isLegacyFunnelsExclusion` never runs. Renaming the filter keys
without converting the exclusions therefore moves a notebook from the first branch to the
second rather than off both, which leaves `exlusionEntityToNode` load-bearing.

Running it is idempotent: a rewrite only fires while a legacy key is present, so an interrupted
run can be repeated.
"""

import json
from collections import Counter
from typing import Any

from django.db.models import QuerySet

from posthog.dataclasses import frozen
from posthog.models import Team

from products.notebooks.backend.models import Notebook

MAX_BACKFILL_BATCH_SIZE = 500

# Legacy snake_case insight-filter keys, mapped to the camelCase field each became.
FILTER_KEY_RENAMES: dict[str, dict[str, str]] = {
    "trendsFilter": {
        "smoothing_intervals": "smoothingIntervals",
        "show_legend": "showLegend",
        "show_alert_threshold_lines": "showAlertThresholdLines",
        "aggregation_axis_format": "aggregationAxisFormat",
        "aggregation_axis_prefix": "aggregationAxisPrefix",
        "aggregation_axis_postfix": "aggregationAxisPostfix",
        "decimal_places": "decimalPlaces",
        "x_axis_label": "xAxisLabel",
        "y_axis_label": "yAxisLabel",
        "show_values_on_series": "showValuesOnSeries",
        "show_percent_stack_view": "showPercentStackView",
        "show_labels_on_series": "showLabelsOnSeries",
        "y_axis_scale_type": "yAxisScaleType",
        "show_multiple_y_axes": "showMultipleYAxes",
    },
    "funnelsFilter": {
        "funnel_viz_type": "funnelVizType",
        "funnel_order_type": "funnelOrderType",
        "funnel_from_step": "funnelFromStep",
        "funnel_to_step": "funnelToStep",
        "funnel_window_interval_unit": "funnelWindowIntervalUnit",
        "funnel_window_interval": "funnelWindowInterval",
        "funnel_step_reference": "funnelStepReference",
        "breakdown_attribution_type": "breakdownAttributionType",
        "breakdown_attribution_value": "breakdownAttributionValue",
        "bin_count": "binCount",
        "funnel_aggregate_by_hogql": "funnelAggregateByHogQL",
    },
    "retentionFilter": {
        "retention_type": "retentionType",
        "retention_reference": "retentionReference",
        "total_intervals": "totalIntervals",
        "returning_entity": "returningEntity",
        "target_entity": "targetEntity",
        "mean_retention_calculation": "meanRetentionCalculation",
    },
    "pathsFilter": {
        "paths_hogql_expression": "pathsHogQLExpression",
        "include_event_types": "includeEventTypes",
        "start_point": "startPoint",
        "end_point": "endPoint",
        "path_groupings": "pathGroupings",
        "exclude_events": "excludeEvents",
        "step_limit": "stepLimit",
        "path_replacements": "pathReplacements",
        "local_path_cleaning_filters": "localPathCleaningFilters",
        "edge_limit": "edgeLimit",
        "min_edge_weight": "minEdgeWeight",
        "max_edge_weight": "maxEdgeWeight",
    },
    "stickinessFilter": {
        "show_legend": "showLegend",
        "show_values_on_series": "showValuesOnSeries",
        "computed_as": "computedAs",
    },
    "lifecycleFilter": {
        "show_legend": "showLegend",
        "show_values_on_series": "showValuesOnSeries",
    },
}

KIND_TO_FILTER_KEY = {
    "TrendsQuery": "trendsFilter",
    "FunnelsQuery": "funnelsFilter",
    "RetentionQuery": "retentionFilter",
    "PathsQuery": "pathsFilter",
    "StickinessQuery": "stickinessFilter",
    "LifecycleQuery": "lifecycleFilter",
}

# `compare` and `compare_to` moved off the insight filter onto a node-level `compareFilter`,
# which keeps the snake_case `compare_to` name. Only these two kinds ever carried them.
COMPARE_KEYS = ("compare", "compare_to")
KINDS_WITH_COMPARE = {"TrendsQuery", "StickinessQuery"}

# The breakdown moved from a `breakdown` object on the query into `breakdownFilter`.
# BreakdownFilter keeps snake_case field names, so this is a move rather than a rename.
BREAKDOWN_KEYS = (
    "breakdown",
    "breakdown_type",
    "breakdown_normalize_url",
    "breakdowns",
    "breakdown_group_type_index",
    "breakdown_limit",
)
# Only trends reads these two, matching the `isTrends` argument of `breakdownFilterToQuery`.
TRENDS_ONLY_BREAKDOWN_KEYS = ("breakdown_histogram_bin_count", "breakdown_hide_other_aggregation")
KINDS_WITH_BREAKDOWN = {"TrendsQuery", "FunnelsQuery"}

# `hidden_legend_keys` became two different fields. Trends and stickiness keep the numeric
# series indexes; funnels keep the named breakdown values.
HIDDEN_LEGEND_KEYS = "hidden_legend_keys"
HIDDEN_LEGEND_INDEXES = "hiddenLegendIndexes"
HIDDEN_LEGEND_BREAKDOWNS = "hiddenLegendBreakdowns"

# Fields `RetentionEntity` accepts. A legacy retention entity can also carry keys that never
# existed on `RetentionEntity`, such as `math`, and the model forbids extra fields, so those
# keys have to go. `sanitizeRetentionEntity` in the browser keeps a shorter list and so drops
# `properties`, which is a real filter on the event, so stored notebooks would lose their
# filters that way. This keeps every field the current schema accepts.
RETENTION_ENTITY_KEYS = frozenset(
    {
        "aggregation_target_field",
        "custom_name",
        "id",
        "kind",
        "name",
        "order",
        "properties",
        "table_name",
        "timestamp_field",
        "type",
        "uuid",
    }
)
LEGACY_RETENTION_ENTITY_KEYS = ("returning_entity", "target_entity")

# `funnel_paths` and `funnel_filter` fold into a separate `funnelPathsFilter`, which needs both
# keys. No stored notebook has `funnel_paths` (measured 2026-09-08), so no `funnelPathsFilter`
# can be built, and `pathsFilterToQuery` already drops both keys on every load today. Dropping
# them here therefore matches what a reader currently sees, and it is what lets the census
# reach zero for paths.
DROPPED_PATHS_KEYS = ("funnel_paths", "funnel_filter")


@frozen
class NotebookRef:
    team_id: int
    short_id: str


@frozen
class NotebookContentRewrite:
    content: dict[str, Any] | None
    unparseable_queries: int


@frozen
class NotebookLegacyFilterBackfill:
    scanned: int
    rewritten: int
    unparseable_queries: int
    shapes: dict[str, int]
    rewritten_notebooks: tuple[NotebookRef, ...]
    dry_run: bool


def rewrite_source(source: dict[str, Any], shapes: Counter) -> bool:
    """Rewrite one `InsightVizNode.source` in place. Returns True when something changed."""
    kind = str(source.get("kind"))
    filter_key = KIND_TO_FILTER_KEY.get(kind)
    changed = False

    insight_filter = source.get(filter_key) if filter_key else None
    if filter_key and isinstance(insight_filter, dict):
        rewritten = _rename_keys(insight_filter, FILTER_KEY_RENAMES[filter_key])
        rewritten = _rewrite_hidden_legend_keys(rewritten, kind)

        if kind in KINDS_WITH_COMPARE:
            rewritten, compare_filter = _extract_compare_filter(rewritten)
            if compare_filter:
                shapes["compare"] += 1
                # An existing `compareFilter` is the current-schema value, so it wins over a
                # stale copy on the insight filter.
                if not source.get("compareFilter"):
                    source["compareFilter"] = compare_filter

        if filter_key == "pathsFilter":
            dropped = {key for key in DROPPED_PATHS_KEYS if key in rewritten}
            if dropped:
                shapes["paths_funnel_keys_dropped"] += 1
                rewritten = {k: v for k, v in rewritten.items() if k not in dropped}

        if filter_key == "funnelsFilter":
            converted = _convert_legacy_exclusions(rewritten)
            if converted is not rewritten:
                shapes["funnels_exclusion"] += 1
                rewritten = converted

        if rewritten != insight_filter:
            source[filter_key] = rewritten
            shapes[filter_key] += 1
            changed = True

    if kind in KINDS_WITH_BREAKDOWN and isinstance(source.get("breakdown"), dict):
        _move_breakdown(source, kind)
        shapes["breakdown"] += 1
        changed = True

    return changed


def rewrite_notebook_content(content: Any, shapes: Counter) -> NotebookContentRewrite:
    """Rewrite the top-level nodes of one notebook's content.

    `content` is None when nothing needed rewriting. `unparseable_queries` is reported either
    way, so a notebook whose only legacy node is an unreadable string still shows up in the
    run's totals.
    """
    if not isinstance(content, dict) or not isinstance(content.get("content"), list):
        return NotebookContentRewrite(content=None, unparseable_queries=0)

    new_nodes: list[Any] = []
    changed = False
    unparseable = 0

    for node in content["content"]:
        rewritten_node, node_changed, node_unparseable = _rewrite_node(node, shapes)
        unparseable += node_unparseable
        changed = changed or node_changed
        new_nodes.append(rewritten_node)

    return NotebookContentRewrite(
        content={**content, "content": new_nodes} if changed else None,
        unparseable_queries=unparseable,
    )


def backfill_notebook_legacy_insight_filters(
    *,
    team_id: int | None = None,
    short_ids: list[str] | None = None,
    dry_run: bool = True,
    batch_size: int | None = None,
    include_deleted: bool = False,
) -> NotebookLegacyFilterBackfill:
    _validate_team_id(team_id)
    batch_size = _validate_batch_size(batch_size)

    queryset = _notebook_scope(team_id, short_ids, include_deleted)
    shapes: Counter = Counter()
    scanned = 0
    unparseable = 0
    rewritten: list[NotebookRef] = []

    for notebook in queryset.iterator(chunk_size=100):
        scanned += 1
        result = rewrite_notebook_content(notebook.content, shapes)
        unparseable += result.unparseable_queries
        if result.content is None:
            continue

        rewritten.append(NotebookRef(team_id=notebook.team_id, short_id=notebook.short_id))

        if not dry_run:
            notebook.content = result.content
            # `last_modified_at` has a create-time default rather than `auto_now`, so writing
            # only `content` leaves the notebook's own edit history untouched. `version` is the
            # editor's conflict counter and a backfill is not a user edit, so it stays put too.
            notebook.save(update_fields=["content"])

        if batch_size is not None and len(rewritten) >= batch_size:
            break

    return NotebookLegacyFilterBackfill(
        scanned=scanned,
        rewritten=len(rewritten),
        unparseable_queries=unparseable,
        shapes=dict(shapes),
        rewritten_notebooks=tuple(rewritten),
        dry_run=dry_run,
    )


def _rewrite_node(node: Any, shapes: Counter) -> tuple[Any, bool, int]:
    if not isinstance(node, dict):
        return node, False, 0

    attrs = node.get("attrs")
    if not isinstance(attrs, dict) or "query" not in attrs:
        return node, False, 0

    raw_query = attrs["query"]
    stored_as_string = isinstance(raw_query, str)

    if stored_as_string:
        try:
            query = json.loads(raw_query)
        except (ValueError, TypeError):
            return node, False, 1
    else:
        query = raw_query

    if not isinstance(query, dict) or query.get("kind") != "InsightVizNode":
        return node, False, 0

    source = query.get("source")
    if not isinstance(source, dict):
        return node, False, 0

    query = json.loads(json.dumps(query))
    if not rewrite_source(query["source"], shapes):
        return node, False, 0

    new_query = json.dumps(query, separators=(",", ":")) if stored_as_string else query
    return {**node, "attrs": {**attrs, "query": new_query}}, True, 0


def _rename_keys(insight_filter: dict, renames: dict[str, str]) -> dict:
    renamed = {}
    for key, value in insight_filter.items():
        new_key = renames.get(key, key)
        # An already-migrated query wins over a stale legacy key, so a filter holding both
        # keeps the value the current schema uses.
        if new_key != key and new_key in insight_filter:
            continue
        if key in LEGACY_RETENTION_ENTITY_KEYS and isinstance(value, dict):
            value = {k: v for k, v in value.items() if k in RETENTION_ENTITY_KEYS}
        renamed[new_key] = value
    return renamed


def _rewrite_hidden_legend_keys(insight_filter: dict, kind: str) -> dict:
    hidden = insight_filter.get(HIDDEN_LEGEND_KEYS)
    if not isinstance(hidden, dict):
        return insight_filter

    if kind == "FunnelsQuery":
        new_key: str = HIDDEN_LEGEND_BREAKDOWNS
        new_value: Any = [key for key, value in hidden.items() if not str(key).isdigit() and value is True]
    else:
        new_key = HIDDEN_LEGEND_INDEXES
        new_value = [int(key) for key, value in hidden.items() if str(key).isdigit() and value is True]

    rewritten = {k: v for k, v in insight_filter.items() if k != HIDDEN_LEGEND_KEYS}
    if new_value and new_key not in rewritten:
        rewritten[new_key] = new_value
    return rewritten


def _convert_legacy_exclusions(insight_filter: dict) -> dict:
    exclusions = insight_filter.get("exclusions")
    if not isinstance(exclusions, list):
        return insight_filter
    if not any(isinstance(entity, dict) and "type" in entity for entity in exclusions):
        return insight_filter
    return {**insight_filter, "exclusions": [_exclusion_entity_to_node(entity) for entity in exclusions]}


def _exclusion_entity_to_node(entity: Any) -> Any:
    if not isinstance(entity, dict) or "type" not in entity:
        return entity

    entity_type = entity.get("type")
    if entity_type == "events":
        node: dict[str, Any] = {"kind": "EventsNode", "event": entity.get("id")}
    elif entity_type == "actions":
        node = {"kind": "ActionsNode", "id": entity.get("id")}
    else:
        # A funnel exclusion has no data warehouse member in the current schema, so any other
        # type has no node to become. Leaving the entity alone keeps the stored value readable.
        return entity

    # `include_properties` is false and math is unavailable for exclusions, so the browser
    # converter carries across only these two of the entity's own fields.
    for key in ("name", "custom_name"):
        if entity.get(key) is not None:
            node[key] = entity[key]

    for legacy_key, new_key in (("funnel_from_step", "funnelFromStep"), ("funnel_to_step", "funnelToStep")):
        if entity.get(legacy_key) is not None:
            node[new_key] = entity[legacy_key]

    return node


def _extract_compare_filter(insight_filter: dict) -> tuple[dict, dict]:
    compare_filter = {key: insight_filter[key] for key in COMPARE_KEYS if key in insight_filter}
    if not compare_filter:
        return insight_filter, {}
    remaining = {key: value for key, value in insight_filter.items() if key not in COMPARE_KEYS}
    return remaining, compare_filter


def _move_breakdown(source: dict, kind: str) -> None:
    breakdown = source.pop("breakdown")
    keys = BREAKDOWN_KEYS + (TRENDS_ONLY_BREAKDOWN_KEYS if kind == "TrendsQuery" else ())
    moved = {key: breakdown[key] for key in keys if key in breakdown}

    existing = source.get("breakdownFilter")
    if isinstance(existing, dict):
        # Keys already in `breakdownFilter` win. The browser converter replaces the whole
        # filter instead, which would drop a current-schema breakdown in favor of a stale one.
        # A few stored notebooks hold both (measured 2026-09-08).
        moved = {**moved, **existing}

    if moved:
        source["breakdownFilter"] = moved


def _validate_team_id(team_id: int | None) -> None:
    if team_id is not None and not Team.objects.filter(id=team_id).exists():
        raise ValueError(f"Team {team_id} does not exist")


def _validate_batch_size(batch_size: int | None) -> int | None:
    if batch_size is None:
        return None
    if batch_size < 1:
        raise ValueError("Batch size must be at least 1")
    if batch_size > MAX_BACKFILL_BATCH_SIZE:
        raise ValueError(f"Batch size must be {MAX_BACKFILL_BATCH_SIZE} or less")
    return batch_size


def _notebook_scope(team_id: int | None, short_ids: list[str] | None, include_deleted: bool) -> QuerySet[Notebook]:
    queryset = Notebook.objects.all()
    if not include_deleted:
        queryset = queryset.filter(deleted=False)
    if team_id is not None:
        queryset = queryset.filter(team_id=team_id)
    if short_ids:
        queryset = queryset.filter(short_id__in=short_ids)
    return queryset.only("id", "team_id", "short_id", "content").order_by("team_id", "short_id")
