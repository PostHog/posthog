import json
import importlib
from collections import Counter
from typing import Any

import pytest
from posthog.test.base import BaseTest

from products.notebooks.backend.legacy_insight_filters import (
    backfill_notebook_legacy_insight_filters,
    rewrite_notebook_content,
    rewrite_source,
)
from products.notebooks.backend.models import Notebook


def _viz(source: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "InsightVizNode", "source": source}


def _notebook_content(query: Any) -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "ph-query", "attrs": {"nodeId": "abc", "query": query}}]}


def _rewrite(source: dict[str, Any]) -> tuple[dict[str, Any], Counter]:
    shapes: Counter = Counter()
    changed = rewrite_source(source, shapes)
    return source, shapes if changed else Counter()


@pytest.mark.parametrize(
    "kind,filter_key,legacy,expected",
    [
        (
            "TrendsQuery",
            "trendsFilter",
            {"show_legend": True, "aggregation_axis_format": "percentage", "decimal_places": 2},
            {"showLegend": True, "aggregationAxisFormat": "percentage", "decimalPlaces": 2},
        ),
        (
            "FunnelsQuery",
            "funnelsFilter",
            {"funnel_viz_type": "steps", "funnel_window_interval": 14, "bin_count": 5},
            {"funnelVizType": "steps", "funnelWindowInterval": 14, "binCount": 5},
        ),
        (
            "RetentionQuery",
            "retentionFilter",
            {"retention_type": "retention_first_time", "total_intervals": 11},
            {"retentionType": "retention_first_time", "totalIntervals": 11},
        ),
        (
            "PathsQuery",
            "pathsFilter",
            {"include_event_types": ["$pageview"], "start_point": "/home", "edge_limit": 50},
            {"includeEventTypes": ["$pageview"], "startPoint": "/home", "edgeLimit": 50},
        ),
        (
            "StickinessQuery",
            "stickinessFilter",
            {"show_values_on_series": True, "computed_as": "distinct_id"},
            {"showValuesOnSeries": True, "computedAs": "distinct_id"},
        ),
        ("LifecycleQuery", "lifecycleFilter", {"show_values_on_series": True}, {"showValuesOnSeries": True}),
    ],
)
def test_legacy_keys_are_renamed(kind, filter_key, legacy, expected):
    source = {"kind": kind, filter_key: legacy}
    rewritten, _ = _rewrite(source)
    assert rewritten == {"kind": kind, filter_key: expected}


@pytest.mark.parametrize(
    "kind,filter_key,current",
    [
        ("TrendsQuery", "trendsFilter", {"showLegend": True, "breakdown_histogram_bin_count": 10}),
        ("FunnelsQuery", "funnelsFilter", {"funnelVizType": "steps", "layout": "vertical"}),
        ("RetentionQuery", "retentionFilter", {"retentionType": "retention_recurring", "period": "Week"}),
        ("PathsQuery", "pathsFilter", {"includeEventTypes": ["$pageview"]}),
        ("StickinessQuery", "stickinessFilter", {"showLegend": False}),
        ("LifecycleQuery", "lifecycleFilter", {"toggledLifecycles": ["new"]}),
        ("HogQLQuery", "query", {"not": "an insight filter"}),
    ],
)
def test_current_shape_is_left_alone(kind, filter_key, current):
    source = {"kind": kind, filter_key: dict(current)}
    shapes: Counter = Counter()
    assert rewrite_source(source, shapes) is False
    assert source == {"kind": kind, filter_key: current}
    assert shapes == Counter()


@pytest.mark.parametrize("kind,filter_key", [("TrendsQuery", "trendsFilter"), ("StickinessQuery", "stickinessFilter")])
def test_compare_moves_onto_compare_filter(kind, filter_key):
    source = {"kind": kind, filter_key: {"compare": True, "compare_to": "-1w", "show_legend": True}}
    rewritten, _ = _rewrite(source)
    assert rewritten == {
        "kind": kind,
        filter_key: {"showLegend": True},
        "compareFilter": {"compare": True, "compare_to": "-1w"},
    }


def test_existing_compare_filter_wins():
    source = {
        "kind": "TrendsQuery",
        "trendsFilter": {"compare": False},
        "compareFilter": {"compare": True, "compare_to": "-1m"},
    }
    rewritten, _ = _rewrite(source)
    assert rewritten["compareFilter"] == {"compare": True, "compare_to": "-1m"}
    assert rewritten["trendsFilter"] == {}


def test_compare_on_a_compare_filter_is_not_treated_as_legacy():
    source = {"kind": "TrendsQuery", "compareFilter": {"compare": True}, "trendsFilter": {"showLegend": True}}
    shapes: Counter = Counter()
    assert rewrite_source(source, shapes) is False


@pytest.mark.parametrize("kind", ["TrendsQuery", "FunnelsQuery"])
def test_breakdown_moves_onto_breakdown_filter(kind):
    source = {"kind": kind, "breakdown": {"breakdown": "$browser", "breakdown_type": "event"}}
    rewritten, _ = _rewrite(source)
    assert rewritten == {"kind": kind, "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event"}}


def test_trends_only_breakdown_keys_are_dropped_for_funnels():
    breakdown = {
        "breakdown": "$browser",
        "breakdown_type": "event",
        "breakdown_histogram_bin_count": 10,
        "breakdown_hide_other_aggregation": True,
    }

    trends, _ = _rewrite({"kind": "TrendsQuery", "breakdown": dict(breakdown)})
    assert trends["breakdownFilter"] == breakdown

    funnels, _ = _rewrite({"kind": "FunnelsQuery", "breakdown": dict(breakdown)})
    assert funnels["breakdownFilter"] == {"breakdown": "$browser", "breakdown_type": "event"}


def test_existing_breakdown_filter_keys_win():
    source = {
        "kind": "TrendsQuery",
        "breakdown": {"breakdown": "$os", "breakdown_type": "event", "breakdown_limit": 5},
        "breakdownFilter": {"breakdown": "$browser"},
    }
    rewritten, _ = _rewrite(source)
    assert rewritten == {
        "kind": "TrendsQuery",
        "breakdownFilter": {"breakdown": "$browser", "breakdown_type": "event", "breakdown_limit": 5},
    }


def test_empty_breakdown_object_is_removed_without_adding_a_filter():
    rewritten, _ = _rewrite({"kind": "TrendsQuery", "breakdown": {}})
    assert rewritten == {"kind": "TrendsQuery"}


def test_scalar_breakdown_is_left_alone():
    source = {"kind": "TrendsQuery", "breakdown": "$browser"}
    shapes: Counter = Counter()
    assert rewrite_source(source, shapes) is False
    assert source == {"kind": "TrendsQuery", "breakdown": "$browser"}


def test_retention_entities_keep_valid_fields_and_lose_unknown_ones():
    source = {
        "kind": "RetentionQuery",
        "retentionFilter": {
            "target_entity": {
                "id": "$pageview",
                "type": "events",
                "properties": [{"key": "$browser", "value": "Chrome"}],
                "math": "total",
            },
            "returning_entity": {"id": "$pageview", "type": "events"},
        },
    }
    rewritten, _ = _rewrite(source)
    assert rewritten["retentionFilter"] == {
        "targetEntity": {"id": "$pageview", "type": "events", "properties": [{"key": "$browser", "value": "Chrome"}]},
        "returningEntity": {"id": "$pageview", "type": "events"},
    }


@pytest.mark.parametrize(
    "kind,filter_key,expected_key,expected_value",
    [
        ("TrendsQuery", "trendsFilter", "hiddenLegendIndexes", [0, 2]),
        ("StickinessQuery", "stickinessFilter", "hiddenLegendIndexes", [0, 2]),
    ],
)
def test_hidden_legend_keys_become_indexes(kind, filter_key, expected_key, expected_value):
    source = {"kind": kind, filter_key: {"hidden_legend_keys": {"0": True, "1": False, "2": True}}}
    rewritten, _ = _rewrite(source)
    assert rewritten[filter_key] == {expected_key: expected_value}


def test_hidden_legend_keys_become_breakdowns_for_funnels():
    source = {"kind": "FunnelsQuery", "funnelsFilter": {"hidden_legend_keys": {"Chrome": True, "Firefox": False}}}
    rewritten, _ = _rewrite(source)
    assert rewritten["funnelsFilter"] == {"hiddenLegendBreakdowns": ["Chrome"]}


def test_paths_funnel_keys_are_dropped():
    source = {"kind": "PathsQuery", "pathsFilter": {"funnel_filter": {"a": 1}, "step_limit": 4}}
    rewritten, shapes = _rewrite(source)
    assert rewritten["pathsFilter"] == {"stepLimit": 4}
    assert shapes["paths_funnel_keys_dropped"] == 1


def test_legacy_events_exclusion_becomes_an_events_node():
    source = {
        "kind": "FunnelsQuery",
        "funnelsFilter": {
            "exclusions": [
                {
                    "id": "$pageleave",
                    "name": "$pageleave",
                    "type": "events",
                    "order": 0,
                    "uuid": "abc",
                    "funnel_from_step": 0,
                    "funnel_to_step": 1,
                }
            ]
        },
    }
    rewritten, shapes = _rewrite(source)
    assert rewritten["funnelsFilter"]["exclusions"] == [
        {"kind": "EventsNode", "event": "$pageleave", "name": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1}
    ]
    assert shapes["funnels_exclusion"] == 1


def test_legacy_actions_exclusion_becomes_an_actions_node():
    source = {
        "kind": "FunnelsQuery",
        "funnelsFilter": {
            "exclusions": [{"id": 42, "type": "actions", "order": 1, "funnel_from_step": 1, "funnel_to_step": 2}]
        },
    }
    rewritten, _ = _rewrite(source)
    assert rewritten["funnelsFilter"]["exclusions"] == [
        {"kind": "ActionsNode", "id": 42, "funnelFromStep": 1, "funnelToStep": 2}
    ]


def test_legacy_filter_keys_and_exclusions_convert_in_one_pass():
    # The browser reaches exclusions through an `else if`, so renaming the filter keys without
    # converting the exclusions moves the notebook to the second branch instead of off both,
    # and leaves `exlusionEntityToNode` load-bearing.
    source = {
        "kind": "FunnelsQuery",
        "funnelsFilter": {
            "funnel_viz_type": "steps",
            "exclusions": [{"id": "$pageleave", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1}],
        },
    }
    rewritten, _ = _rewrite(source)
    assert rewritten["funnelsFilter"] == {
        "funnelVizType": "steps",
        "exclusions": [{"kind": "EventsNode", "event": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1}],
    }


def test_current_exclusions_are_left_alone():
    source = {
        "kind": "FunnelsQuery",
        "funnelsFilter": {
            "funnelVizType": "steps",
            "exclusions": [{"kind": "EventsNode", "event": "$pageleave", "funnelFromStep": 0, "funnelToStep": 1}],
        },
    }
    shapes: Counter = Counter()
    assert rewrite_source(source, shapes) is False
    assert shapes == Counter()


def test_string_stored_query_is_rewritten_and_stays_a_string():
    stored = json.dumps(_viz({"kind": "TrendsQuery", "trendsFilter": {"show_legend": True}}), separators=(",", ":"))
    shapes: Counter = Counter()

    result = rewrite_notebook_content(_notebook_content(stored), shapes)

    assert result.content is not None
    rewritten_query = result.content["content"][0]["attrs"]["query"]
    assert isinstance(rewritten_query, str)
    assert json.loads(rewritten_query)["source"]["trendsFilter"] == {"showLegend": True}
    assert result.unparseable_queries == 0


def test_unparseable_query_string_is_left_untouched_and_counted():
    shapes: Counter = Counter()
    content = _notebook_content('{"kind":"InsightVizNode","source":{"kind":"TrendsQuery","q":"a "b"}')

    result = rewrite_notebook_content(content, shapes)

    assert result.content is None
    assert result.unparseable_queries == 1


def test_object_stored_query_is_rewritten_in_place():
    shapes: Counter = Counter()
    content = _notebook_content(_viz({"kind": "TrendsQuery", "trendsFilter": {"show_legend": True}}))

    result = rewrite_notebook_content(content, shapes)

    assert result.content is not None
    assert result.content["content"][0]["attrs"]["query"]["source"]["trendsFilter"] == {"showLegend": True}
    assert shapes["trendsFilter"] == 1


def test_nested_node_is_not_reached():
    # `migrate` maps only top-level nodes, so a legacy shape nested deeper was never converted
    # and rewriting it would change what a reader sees rather than preserve it.
    shapes: Counter = Counter()
    nested = {
        "type": "doc",
        "content": [
            {
                "type": "column",
                "content": [
                    {
                        "type": "ph-query",
                        "attrs": {"query": _viz({"kind": "TrendsQuery", "trendsFilter": {"show_legend": True}})},
                    }
                ],
            }
        ],
    }
    assert rewrite_notebook_content(nested, shapes).content is None


@pytest.mark.parametrize("content", [None, {}, {"type": "doc"}, {"type": "doc", "content": "not a list"}])
def test_unusable_content_does_not_raise(content):
    assert rewrite_notebook_content(content, Counter()).content is None


def test_rewrite_is_idempotent():
    shapes: Counter = Counter()
    content = _notebook_content(_viz({"kind": "TrendsQuery", "trendsFilter": {"show_legend": True}}))

    once = rewrite_notebook_content(content, shapes).content
    assert once is not None

    assert rewrite_notebook_content(once, Counter()).content is None


class TestNotebookLegacyFilterBackfill(BaseTest):
    def _create(self, short_id: str, filters: dict[str, Any], **kwargs: Any) -> Notebook:
        return Notebook.objects.create(
            team=self.team,
            short_id=short_id,
            content=_notebook_content(_viz({"kind": "TrendsQuery", "trendsFilter": filters})),
            **kwargs,
        )

    def test_dry_run_reports_without_writing(self):
        notebook = self._create("legacy01", {"show_legend": True})

        result = backfill_notebook_legacy_insight_filters(team_id=self.team.id)

        assert result.dry_run is True
        assert result.rewritten == 1
        assert result.shapes == {"trendsFilter": 1}
        notebook.refresh_from_db()
        assert notebook.content["content"][0]["attrs"]["query"]["source"]["trendsFilter"] == {"show_legend": True}

    def test_write_persists_and_leaves_edit_history_alone(self):
        notebook = self._create("legacy02", {"show_legend": True})
        modified_before = notebook.last_modified_at
        version_before = notebook.version

        result = backfill_notebook_legacy_insight_filters(team_id=self.team.id, dry_run=False)

        assert result.rewritten == 1
        notebook.refresh_from_db()
        assert notebook.content["content"][0]["attrs"]["query"]["source"]["trendsFilter"] == {"showLegend": True}
        assert notebook.last_modified_at == modified_before
        assert notebook.version == version_before

    def test_current_shape_notebook_is_scanned_but_not_rewritten(self):
        self._create("current01", {"showLegend": True})

        result = backfill_notebook_legacy_insight_filters(team_id=self.team.id, dry_run=False)

        assert result.scanned == 1
        assert result.rewritten == 0
        assert result.rewritten_notebooks == ()

    def test_short_id_filter_restricts_the_scope(self):
        self._create("legacy03", {"show_legend": True})
        other = self._create("legacy04", {"show_legend": True})

        result = backfill_notebook_legacy_insight_filters(team_id=self.team.id, short_ids=["legacy03"], dry_run=False)

        assert result.rewritten == 1
        assert [ref.short_id for ref in result.rewritten_notebooks] == ["legacy03"]
        other.refresh_from_db()
        assert other.content["content"][0]["attrs"]["query"]["source"]["trendsFilter"] == {"show_legend": True}

    def test_deleted_notebooks_are_skipped_unless_asked_for(self):
        self._create("deleted01", {"show_legend": True}, deleted=True)

        assert backfill_notebook_legacy_insight_filters(team_id=self.team.id).rewritten == 0
        assert backfill_notebook_legacy_insight_filters(team_id=self.team.id, include_deleted=True).rewritten == 1

    def test_batch_size_stops_early(self):
        self._create("legacy05", {"show_legend": True})
        self._create("legacy06", {"show_legend": True})

        result = backfill_notebook_legacy_insight_filters(team_id=self.team.id, batch_size=1, dry_run=False)

        assert result.rewritten == 1

    def test_unknown_team_is_rejected(self):
        with pytest.raises(ValueError):
            backfill_notebook_legacy_insight_filters(team_id=999999999)

    def test_oversized_batch_is_rejected(self):
        with pytest.raises(ValueError):
            backfill_notebook_legacy_insight_filters(team_id=self.team.id, batch_size=10_000)


def test_migration_copy_matches_this_module():
    # Migration 0018 carries its own copy of the transform, so that deleting this module later
    # cannot break a replay. This is what catches the two copies drifting apart.
    migration = importlib.import_module("products.notebooks.backend.migrations.0018_backfill_legacy_insight_filters")

    fixtures: list[dict[str, Any]] = [
        {"kind": "TrendsQuery", "trendsFilter": {"show_legend": True, "compare": True, "decimal_places": 2}},
        {
            "kind": "FunnelsQuery",
            "funnelsFilter": {
                "funnel_viz_type": "steps",
                "exclusions": [{"id": "$pageleave", "type": "events", "funnel_from_step": 0, "funnel_to_step": 1}],
            },
        },
        {
            "kind": "RetentionQuery",
            "retentionFilter": {
                "retention_type": "retention_first_time",
                "target_entity": {"id": "$pageview", "type": "events", "math": "total"},
            },
        },
        {"kind": "PathsQuery", "pathsFilter": {"funnel_filter": {"a": 1}, "step_limit": 4}},
        {"kind": "StickinessQuery", "stickinessFilter": {"hidden_legend_keys": {"0": True, "1": False}}},
        {"kind": "LifecycleQuery", "lifecycleFilter": {"show_values_on_series": True}},
        {"kind": "TrendsQuery", "breakdown": {"breakdown": "$browser", "breakdown_type": "event"}},
        {"kind": "TrendsQuery", "trendsFilter": {"showLegend": True}},
    ]

    for source in fixtures:
        content = {"type": "doc", "content": [{"type": "ph-query", "attrs": {"query": _viz(source)}}]}

        from_module = rewrite_notebook_content(json.loads(json.dumps(content)), Counter()).content
        from_migration = migration._rewrite_content(json.loads(json.dumps(content)))

        assert from_module == from_migration, f"copies disagree on {source['kind']}"
