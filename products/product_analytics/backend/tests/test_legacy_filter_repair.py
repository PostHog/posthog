from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import InsightVizNode, QuerySchemaRoot

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query

from products.product_analytics.backend.legacy_filter_repair import repair_filters

# Filters that already convert. Repair must leave the resulting query byte-identical: an alias that
# is too eager would silently rewrite insights that work.
ALREADY_VALID: list[tuple[str, dict]] = [
    ("trends", {"insight": "TRENDS", "events": [{"id": "$pageview", "type": "events", "order": 0}]}),
    ("base_math", {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "dau"}]}),
    ("property_math", {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "p95", "math_property": "x"}]}),
    (
        "group_math",
        {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "unique_group", "math_group_type_index": 0}]},
    ),
    # Converts and validates without its companion field, so repair has no business touching it.
    ("group_math_without_index", {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "unique_group"}]}),
    ("hogql_math_without_expression", {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "hogql"}]}),
    (
        "funnels",
        {
            "insight": "FUNNELS",
            "events": [{"id": "a", "order": 0}, {"id": "b", "order": 1}],
            "funnel_order_type": "strict",
        },
    ),
    (
        "retention",
        {
            "insight": "RETENTION",
            "period": "Week",
            "retention_type": "retention_first_time",
            "target_entity": {"id": "a", "type": "events"},
        },
    ),
    ("paths", {"insight": "PATHS", "include_event_types": ["$pageview", "custom_event"], "step_limit": 5}),
    ("lifecycle", {"insight": "LIFECYCLE", "events": [{"id": "a", "order": 0}], "toggledLifecycles": ["new"]}),
    ("stickiness", {"shown_as": "Stickiness", "events": [{"id": "a", "order": 0}]}),
    ("breakdown", {"insight": "TRENDS", "breakdown": "$browser", "breakdown_type": "event", "events": [{"id": "a"}]}),
    (
        "entity_properties",
        {
            "insight": "TRENDS",
            "events": [{"id": "a", "properties": [{"key": "x", "value": "1", "operator": "exact", "type": "event"}]}],
        },
    ),
    (
        "old_style_properties",
        {"insight": "TRENDS", "events": [{"id": "a", "properties": {"utm_medium__icontains": "email"}}]},
    ),
    (
        "cohort",
        {"insight": "TRENDS", "properties": [{"key": "id", "value": 42, "type": "cohort"}], "events": [{"id": "a"}]},
    ),
    ("actions", {"insight": "TRENDS", "actions": [{"id": 12, "type": "actions", "order": 0}]}),
    ("empty_shell", {}),
]

# Values `filters` accepted because the column was never validated. Each case is (name, broken
# filters, the repair we expect), and every one must end up convertible.
REPAIRABLE: list[tuple[str, Any, str]] = [
    (
        "math_alias",
        {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "unique_users"}]},
        "math:unique_users->dau",
    ),
    (
        "math_percentile_alias",
        {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "p50", "math_property": "x"}]},
        "math:p50->median",
    ),
    (
        "math_ambiguous_dropped",
        {"insight": "TRENDS", "events": [{"id": "a", "order": 0, "math": "last_value", "math_property": "x"}]},
        "math:last_value->default",
    ),
    (
        "insight_case_variant",
        {"insight": "FUNNEL", "events": [{"id": "a", "order": 0}, {"id": "b", "order": 1}]},
        "insight:FUNNEL->FUNNELS",
    ),
    (
        "insight_display_type",
        {"insight": "NUMBER", "display": "BoldNumber", "events": [{"id": "a", "order": 0}]},
        "insight:NUMBER->TRENDS",
    ),
    ("insight_null", {"insight": None, "events": [{"id": "a", "order": 0}]}, "insight:null->TRENDS"),
    ("insight_unhashable", {"insight": ["TRENDS"], "events": [{"id": "a", "order": 0}]}, "insight:malformed->TRENDS"),
    (
        "event_id_number",
        {"insight": "TRENDS", "events": [{"id": 123, "order": 0, "type": "events"}]},
        "entity.id:coerced-str",
    ),
    ("interval_unknown", {"insight": "TRENDS", "interval": "total", "events": [{"id": "a"}]}, "interval:dropped"),
    (
        "funnel_order_alias",
        {"insight": "FUNNELS", "funnel_order_type": "sequential", "events": [{"id": "a"}, {"id": "b"}]},
        "funnel_order_type:sequential->ordered",
    ),
    (
        "funnel_window_unit_plural",
        {"insight": "FUNNELS", "funnel_window_interval_unit": "seconds", "events": [{"id": "a"}]},
        "funnel_window_interval_unit:seconds->second",
    ),
    (
        "retention_type_alias",
        {"insight": "RETENTION", "retention_type": "retention"},
        "retention_type:retention->retention_recurring",
    ),
    ("retention_period_case", {"insight": "RETENTION", "period": "week"}, "period:week->Week"),
    (
        "breakdown_type_unknown",
        {"insight": "TRENDS", "breakdown": "x", "breakdown_type": "feature", "events": [{"id": "a"}]},
        "breakdown_type:dropped",
    ),
    (
        "path_types_unknown",
        {"insight": "PATHS", "include_event_types": ["$pageview", "some_event_name"]},
        "include_event_types:dropped-unknown",
    ),
    (
        "property_key_spelled_property",
        {
            "insight": "TRENDS",
            "properties": [{"operator": "exact", "property": "$browser", "value": "Chrome"}],
            "events": [{"id": "a"}],
        },
        "property.property->key",
    ),
    (
        "property_operator_alias",
        {
            "insight": "TRENDS",
            "events": [{"id": "a", "properties": [{"key": "x", "value": "1", "operator": "eq", "type": "event"}]}],
        },
        "property.operator:eq->exact",
    ),
    (
        "property_bare_string",
        {"insight": "TRENDS", "properties": ["not-a-filter"], "events": [{"id": "a"}]},
        "properties:dropped-unexpected-format",
    ),
    (
        "property_unknown_element_key",
        {
            "insight": "FUNNELS",
            "events": [{"id": "a", "properties": [{"key": "nope", "value": "x", "type": "element"}]}],
        },
        "property:dropped-unknown-element-key",
    ),
    (
        "entity_properties_nested_group",
        {
            "insight": "FUNNELS",
            "events": [
                {
                    "id": "a",
                    "properties": {
                        "type": "AND",
                        "values": [{"type": "AND", "values": [{"key": "x", "value": "1", "type": "event"}]}],
                    },
                }
            ],
        },
        "entity.properties:flattened",
    ),
    (
        "exclusion_step_string",
        {
            "insight": "FUNNELS",
            "events": [{"id": "a"}, {"id": "b"}],
            "exclusions": [{"id": "c", "funnel_from_step": "0", "funnel_to_step": "1"}],
        },
        "funnel_from_step:coerced-int",
    ),
    ("date_from_number", {"insight": "TRENDS", "date_from": -7, "events": [{"id": "a"}]}, "date_from:coerced-str"),
    (
        "multi_breakdown",
        {"insight": "FUNNELS", "breakdowns": [{"property": "a"}, {"property": "b"}], "events": [{"id": "a"}]},
        "breakdowns:dropped-multiple",
    ),
    ("events_not_a_list", {"insight": "TRENDS", "events": None}, "events:dropped-not-a-list"),
    ("filters_not_a_dict", None, "filters:replaced-non-dict"),
]


def convert(filters: dict) -> dict:
    return InsightVizNode(source=filter_to_query(filters)).model_dump(exclude_none=True)


class TestLegacyFilterRepair(SimpleTestCase):
    @parameterized.expand(ALREADY_VALID)
    def test_leaves_convertible_filters_alone(self, _name: str, filters: dict) -> None:
        repaired, repairs = repair_filters(filters)

        assert repairs == []
        assert convert(repaired) == convert(filters)

    @parameterized.expand(REPAIRABLE)
    def test_repairs_filters_that_cannot_convert(self, _name: str, filters: Any, expected_repair: str) -> None:
        # Each case has to actually be broken, or it is not testing the repair.
        with self.assertRaises(Exception):
            convert(filters)

        repaired, repairs = repair_filters(filters)

        assert expected_repair in repairs
        # A stored query that /query would reject is no better than no query at all.
        QuerySchemaRoot.model_validate(convert(repaired))

    def test_keeps_the_series_when_repairing_one_of_its_events(self) -> None:
        filters = {
            "insight": "TRENDS",
            "events": [
                {"id": "kept", "order": 0, "type": "events"},
                {"id": "repaired", "order": 1, "type": "events", "math": "unique_users"},
            ],
        }

        repaired, _ = repair_filters(filters)

        series = convert(repaired)["source"]["series"]
        assert [s["event"] for s in series] == ["kept", "repaired"]
        assert series[1]["math"] == "dau"

    def test_drops_only_the_unrepairable_property(self) -> None:
        filters = {
            "insight": "TRENDS",
            "events": [
                {
                    "id": "a",
                    "properties": [
                        {"key": "kept", "value": "1", "operator": "exact", "type": "event"},
                        {"key": "dropped", "type": "behavioral", "value": "performed_event"},
                    ],
                }
            ],
        }

        repaired, repairs = repair_filters(filters)

        assert "property:dropped-behavioral" in repairs
        assert [p["key"] for p in repaired["events"][0]["properties"]] == ["kept"]
