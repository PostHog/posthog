"""Rewrite legacy snake_case insight filters in stored notebook content.

PostHog Cloud was backfilled from a toolbox copy of
`backfill_notebook_legacy_insight_filters`, following the pattern the insight backfills use.
A toolbox run cannot reach a self-hosted instance, so this migration carries the same rewrite
to every deployment on upgrade. Without it, a self-hosted notebook holding a legacy filter
would render wrong once the browser converters
(`convertInsightQueriesToNewSchema` in notebook `migrate.ts`) are deleted, because every query
model forbids extra fields and a snake_case key no longer validates.

The transform is copied in rather than imported. Migrations 0530 and 0545 on the `posthog` app
import `filter_to_query` at module scope, and that import is now the last thing keeping a
converter this project wants to delete. A migration has to keep applying years from now, so it
carries its own copy of what it needs.

Runtime: this walks every notebook, because the legacy shapes sit inside
`content.content[*].attrs.query`, and half of them inside a JSON string, so no index or JSONB
operator selects the candidates. It is idempotent, so a repeat run rewrites nothing. On Cloud it
therefore scans and changes nothing, the backfill having already run. If that scan is not wanted
on a Cloud deploy, gate the body on `posthog.cloud_utils.is_cloud`.
"""

import json
from typing import Any

from django.db import migrations

BATCH_SIZE = 500

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

COMPARE_KEYS = ("compare", "compare_to")
KINDS_WITH_COMPARE = {"TrendsQuery", "StickinessQuery"}

BREAKDOWN_KEYS = (
    "breakdown",
    "breakdown_type",
    "breakdown_normalize_url",
    "breakdowns",
    "breakdown_group_type_index",
    "breakdown_limit",
)
TRENDS_ONLY_BREAKDOWN_KEYS = ("breakdown_histogram_bin_count", "breakdown_hide_other_aggregation")
KINDS_WITH_BREAKDOWN = {"TrendsQuery", "FunnelsQuery"}

HIDDEN_LEGEND_KEYS = "hidden_legend_keys"

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

DROPPED_PATHS_KEYS = ("funnel_paths", "funnel_filter")


def _rename_keys(insight_filter: dict, renames: dict[str, str]) -> dict:
    renamed = {}
    for key, value in insight_filter.items():
        new_key = renames.get(key, key)
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
        new_key = "hiddenLegendBreakdowns"
        new_value: Any = [key for key, value in hidden.items() if not str(key).isdigit() and value is True]
    else:
        new_key = "hiddenLegendIndexes"
        new_value = [int(key) for key, value in hidden.items() if str(key).isdigit() and value is True]

    rewritten = {k: v for k, v in insight_filter.items() if k != HIDDEN_LEGEND_KEYS}
    if new_value and new_key not in rewritten:
        rewritten[new_key] = new_value
    return rewritten


def _exclusion_entity_to_node(entity: Any) -> Any:
    if not isinstance(entity, dict) or "type" not in entity:
        return entity

    entity_type = entity.get("type")
    if entity_type == "events":
        node: dict[str, Any] = {"kind": "EventsNode", "event": entity.get("id")}
    elif entity_type == "actions":
        node = {"kind": "ActionsNode", "id": entity.get("id")}
    else:
        return entity

    for key in ("name", "custom_name"):
        if entity.get(key) is not None:
            node[key] = entity[key]
    for legacy_key, new_key in (("funnel_from_step", "funnelFromStep"), ("funnel_to_step", "funnelToStep")):
        if entity.get(legacy_key) is not None:
            node[new_key] = entity[legacy_key]
    return node


def _convert_legacy_exclusions(insight_filter: dict) -> dict:
    exclusions = insight_filter.get("exclusions")
    if not isinstance(exclusions, list):
        return insight_filter
    if not any(isinstance(entity, dict) and "type" in entity for entity in exclusions):
        return insight_filter
    return {**insight_filter, "exclusions": [_exclusion_entity_to_node(entity) for entity in exclusions]}


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
        moved = {**moved, **existing}
    if moved:
        source["breakdownFilter"] = moved


def _rewrite_source(source: dict[str, Any]) -> bool:
    kind = str(source.get("kind"))
    filter_key = KIND_TO_FILTER_KEY.get(kind)
    changed = False

    insight_filter = source.get(filter_key) if filter_key else None
    if filter_key and isinstance(insight_filter, dict):
        rewritten = _rename_keys(insight_filter, FILTER_KEY_RENAMES[filter_key])
        rewritten = _rewrite_hidden_legend_keys(rewritten, kind)

        if kind in KINDS_WITH_COMPARE:
            rewritten, compare_filter = _extract_compare_filter(rewritten)
            if compare_filter and not source.get("compareFilter"):
                source["compareFilter"] = compare_filter

        if filter_key == "pathsFilter":
            rewritten = {k: v for k, v in rewritten.items() if k not in DROPPED_PATHS_KEYS}

        if filter_key == "funnelsFilter":
            rewritten = _convert_legacy_exclusions(rewritten)

        if rewritten != insight_filter:
            source[filter_key] = rewritten
            changed = True

    if kind in KINDS_WITH_BREAKDOWN and isinstance(source.get("breakdown"), dict):
        _move_breakdown(source, kind)
        changed = True

    return changed


def _rewrite_node(node: Any) -> tuple[Any, bool]:
    if not isinstance(node, dict):
        return node, False

    attrs = node.get("attrs")
    if not isinstance(attrs, dict) or "query" not in attrs:
        return node, False

    raw_query = attrs["query"]
    stored_as_string = isinstance(raw_query, str)
    if stored_as_string:
        try:
            query = json.loads(raw_query)
        except (ValueError, TypeError):
            return node, False
    else:
        query = raw_query

    if not isinstance(query, dict) or query.get("kind") != "InsightVizNode":
        return node, False
    if not isinstance(query.get("source"), dict):
        return node, False

    query = json.loads(json.dumps(query))
    if not _rewrite_source(query["source"]):
        return node, False

    new_query = json.dumps(query, separators=(",", ":")) if stored_as_string else query
    return {**node, "attrs": {**attrs, "query": new_query}}, True


def _rewrite_content(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, dict) or not isinstance(content.get("content"), list):
        return None

    new_nodes = []
    changed = False
    for node in content["content"]:
        rewritten_node, node_changed = _rewrite_node(node)
        changed = changed or node_changed
        new_nodes.append(rewritten_node)

    if not changed:
        return None
    return {**content, "content": new_nodes}


def backfill_legacy_insight_filters(apps, schema_editor):
    Notebook = apps.get_model("notebooks", "Notebook")

    pending: list[Any] = []
    for notebook in Notebook.objects.only("id", "content").iterator(chunk_size=100):
        try:
            new_content = _rewrite_content(notebook.content)
        except Exception:
            # One unreadable notebook must not stop an upgrade. Its content stays as stored, and
            # the browser keeps rendering it exactly as it does today.
            continue

        if new_content is None:
            continue

        notebook.content = new_content
        pending.append(notebook)
        if len(pending) >= BATCH_SIZE:
            Notebook.objects.bulk_update(pending, ["content"])
            pending = []

    if pending:
        Notebook.objects.bulk_update(pending, ["content"])


class Migration(migrations.Migration):
    # Rewrites rows in batches rather than holding one transaction over every notebook.
    atomic = False

    dependencies = [
        ("notebooks", "0017_kernelruntime_provisioned_cpu_cores_and_more"),
    ]

    operations = [
        # The rewrite drops keys the current schema cannot express, so reverse is a no-op.
        migrations.RunPython(backfill_legacy_insight_filters, migrations.RunPython.noop),
    ]
