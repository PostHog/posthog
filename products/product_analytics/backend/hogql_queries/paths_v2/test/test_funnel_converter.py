from datetime import datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    EventsNode,
    FunnelConversionWindowTimeUnit,
    FunnelExclusionEventsNode,
    HogQLPropertyFilter,
    PathsV2Filter,
    PathsV2Item,
    PathsV2Query,
    PathsV2StepSource,
    PropertyOperator,
    StepOrderValue,
)

from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.test.test_journeys import journeys_for

from products.product_analytics.backend.hogql_queries.paths_v2.funnel_converter import edge_to_funnels_query
from products.product_analytics.backend.hogql_queries.paths_v2.paths_v2_query_runner import PathsV2QueryRunner

DATE_RANGE = DateRange(date_from="2023-03-01", date_to="2023-03-31")


def _sources(*events: str) -> list[PathsV2StepSource]:
    return [PathsV2StepSource(event=event) for event in events]


def _timeline(*events: str, start: str = "2023-03-10 10:00:00", step_minutes: int = 5) -> list[dict[str, Any]]:
    start_dt = datetime.fromisoformat(start)
    return [
        {
            "event": event,
            "timestamp": (start_dt + timedelta(minutes=i * step_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
        }
        for i, event in enumerate(events)
    ]


def _item(event: str, label: str | None = None) -> PathsV2Item:
    return PathsV2Item(event=event, label=label)


SIMPLE_SOURCES = _sources("a", "b", "c")

# Each case pins the edge contract for one journey shape: the displayed edge, the converted
# funnel, and the hand-derived expected unique-actor count must all agree.
EDGE_CONTRACT_CASES: list[tuple[str, dict[str, Any], dict[str, Any], int, PathsV2Item, PathsV2Item, int]] = [
    (
        "simple_edge",
        {"p1": _timeline("a", "b"), "p2": _timeline("a", "b"), "p3": _timeline("a", "c")},
        {},
        0,
        _item("a"),
        _item("b"),
        2,
    ),
    (
        "loop_revisit",
        {"p1": _timeline("a", "b", "a", "b")},
        {},
        1,
        _item("b"),
        _item("a"),
        1,
    ),
    (
        "collapse_on_repeated_source",
        # The repeated a re-anchors the funnel exactly like collapse merges the repeat.
        {"p1": _timeline("a", "a", "b")},
        {},
        0,
        _item("a"),
        _item("b"),
        1,
    ),
    (
        "collapse_off_self_edge",
        # p2's intervening c breaks the self-edge on both sides.
        {"p1": _timeline("a", "a", "b"), "p2": _timeline("a", "c", "a")},
        {"collapseRepeats": False},
        0,
        _item("a"),
        _item("a"),
        1,
    ),
    (
        "gap_boundary",
        # p1 sits exactly on the gap G, p2 one second beyond it; both engines must draw the same line.
        {
            "p1": [
                {"event": "a", "timestamp": "2023-03-10 10:00:00"},
                {"event": "b", "timestamp": "2023-03-10 10:30:00"},
            ],
            "p2": [
                {"event": "a", "timestamp": "2023-03-11 10:00:00"},
                {"event": "b", "timestamp": "2023-03-11 10:30:01"},
            ],
        },
        {},
        0,
        _item("a"),
        _item("b"),
        1,
    ),
    (
        "intervening_included_item",
        # p2's c is an included path item between a and b, so the edge and the funnel's
        # item-strict exclusion must both drop p2.
        {"p1": _timeline("a", "b"), "p2": _timeline("a", "c", "b")},
        {},
        0,
        _item("a"),
        _item("b"),
        1,
    ),
    (
        "exclusion_reanchors",
        # After the intervening c, the second a re-anchors: the edge exists and the funnel
        # must count the actor rather than dropping them for the earlier exclusion.
        {"p1": _timeline("a", "c", "a", "b")},
        {},
        2,
        _item("a"),
        _item("b"),
        1,
    ),
    (
        "multiple_journeys_same_edge",
        {
            "p1": [
                *_timeline("a", "b"),
                *_timeline("a", "b", start="2023-03-10 14:00:00"),
            ]
        },
        {},
        0,
        _item("a"),
        _item("b"),
        1,
    ),
    (
        "date_range_clipped_journey",
        {
            "p1": [
                {"event": "a", "timestamp": "2023-02-28 23:50:00"},
                {"event": "b", "timestamp": "2023-03-01 00:05:00"},
                {"event": "c", "timestamp": "2023-03-01 00:10:00"},
            ]
        },
        {},
        0,
        _item("b"),
        _item("c"),
        1,
    ),
]


class TestPathsV2EdgeContract(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _edge_count(self, query: PathsV2Query, step_index: int, source: PathsV2Item, target: PathsV2Item) -> float:
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results
        for edge in results.edges:
            if edge.stepIndex == step_index and edge.source == source and edge.target == target:
                return edge.count
        return 0

    def _funnel_count(self, query: PathsV2Query, source: PathsV2Item, target: PathsV2Item) -> float:
        funnels_query = edge_to_funnels_query(query, self.team, source, target)
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results
        return results[1]["count"]

    @parameterized.expand(EDGE_CONTRACT_CASES)
    def test_edge_matches_funnel(
        self,
        _name: str,
        events_by_person: dict[str, list[dict[str, Any]]],
        filter_overrides: dict[str, Any],
        step_index: int,
        source: PathsV2Item,
        target: PathsV2Item,
        expected_count: int,
    ):
        journeys_for(team=self.team, events_by_person=events_by_person)
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(stepSources=SIMPLE_SOURCES, **filter_overrides),
        )

        edge_count = self._edge_count(query, step_index, source, target)
        funnel_count = self._funnel_count(query, source, target)

        self.assertEqual(edge_count, expected_count)
        self.assertEqual(funnel_count, expected_count)

    def test_naming_property_edge_matches_funnel(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "signup", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:05:00", "properties": {"stage": "lead"}},
                ],
                "p2": [
                    {"event": "signup", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:05:00", "properties": {"stage": "won"}},
                ],
                "p3": [
                    {"event": "signup", "timestamp": "2023-03-10 10:00:00"},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:05:00", "properties": {"stage": "won"}},
                    {"event": "stage changed", "timestamp": "2023-03-10 10:10:00", "properties": {"stage": "lead"}},
                ],
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(
                stepSources=[
                    PathsV2StepSource(event="signup"),
                    PathsV2StepSource(event="stage changed", namingProperty="stage"),
                ]
            ),
        )
        source, target = _item("signup"), _item("stage changed", label="lead")

        # Only p1 moves from signup straight to the lead stage; p3's won stage is an included item
        # in between, which the funnel must exclude via the label-derived item.
        self.assertEqual(self._edge_count(query, 0, source, target), 1)
        self.assertEqual(self._funnel_count(query, source, target), 1)

    def test_path_cleaning_edge_matches_funnel(self):
        self.team.path_cleaning_filters = [{"alias": "/item/<id>", "regex": r"/item/\d+"}]
        self.team.save()
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/item/1"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/about"}},
                ],
                "p2": [
                    {"event": "$pageview", "timestamp": "2023-03-10 10:00:00", "properties": {"$pathname": "/item/2"}},
                    {"event": "$pageview", "timestamp": "2023-03-10 10:05:00", "properties": {"$pathname": "/about"}},
                ],
            },
        )
        query = PathsV2Query(dateRange=DATE_RANGE)
        source, target = _item("$pageview", label="/item/<id>"), _item("$pageview", label="/about")

        # Both raw URLs clean into the same item, so the funnel's label filter must apply the
        # same cleaning to match either of them.
        self.assertEqual(self._edge_count(query, 0, source, target), 2)
        self.assertEqual(self._funnel_count(query, source, target), 2)

    def test_property_filters_apply_to_both_sides(self):
        journeys_for(
            team=self.team,
            events_by_person={
                "p1": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00", "properties": {"plan": "paid"}},
                    {"event": "b", "timestamp": "2023-03-10 10:05:00", "properties": {"plan": "paid"}},
                ],
                "p2": [
                    {"event": "a", "timestamp": "2023-03-10 10:00:00", "properties": {"plan": "free"}},
                    {"event": "b", "timestamp": "2023-03-10 10:05:00", "properties": {"plan": "free"}},
                ],
            },
        )
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            properties=[EventPropertyFilter(key="plan", value="paid", operator=PropertyOperator.EXACT)],
            pathsV2Filter=PathsV2Filter(stepSources=SIMPLE_SOURCES),
        )
        source, target = _item("a"), _item("b")

        self.assertEqual(self._edge_count(query, 0, source, target), 1)
        self.assertEqual(self._funnel_count(query, source, target), 1)


class TestEdgeToFunnelsQuery(APIBaseTest):
    def test_converted_funnel_shape(self):
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            filterTestAccounts=True,
            properties=[EventPropertyFilter(key="plan", value="paid", operator=PropertyOperator.EXACT)],
            pathsV2Filter=PathsV2Filter(
                stepSources=[
                    PathsV2StepSource(event="signup"),
                    PathsV2StepSource(event="stage changed", namingProperty="stage"),
                ],
                gapInterval=2,
                gapIntervalUnit=FunnelConversionWindowTimeUnit.HOUR,
            ),
        )

        funnels_query = edge_to_funnels_query(query, self.team, _item("signup"), _item("stage changed", label="lead"))

        assert isinstance(funnels_query.series[0], EventsNode)
        assert isinstance(funnels_query.series[1], EventsNode)
        self.assertEqual(funnels_query.series[0].event, "signup")
        self.assertIsNone(funnels_query.series[0].properties)
        self.assertEqual(funnels_query.series[1].event, "stage changed")
        assert funnels_query.series[1].properties is not None
        label_filter = funnels_query.series[1].properties[0]
        assert isinstance(label_filter, HogQLPropertyFilter)
        self.assertEqual(label_filter.key, "equals(ifNull(toString(properties.stage), ''), 'lead')")

        assert funnels_query.funnelsFilter is not None
        self.assertEqual(funnels_query.funnelsFilter.funnelWindowInterval, 2)
        self.assertEqual(funnels_query.funnelsFilter.funnelWindowIntervalUnit, FunnelConversionWindowTimeUnit.HOUR)
        self.assertEqual(funnels_query.funnelsFilter.funnelOrderType, StepOrderValue.ORDERED)

        assert funnels_query.funnelsFilter.exclusions is not None
        exclusion = funnels_query.funnelsFilter.exclusions[0]
        assert isinstance(exclusion, FunnelExclusionEventsNode)
        self.assertIsNone(exclusion.event)
        self.assertEqual(exclusion.funnelFromStep, 0)
        self.assertEqual(exclusion.funnelToStep, 1)
        assert exclusion.properties is not None
        universe_filter = exclusion.properties[0]
        assert isinstance(universe_filter, HogQLPropertyFilter)
        self.assertIn("in(event, ['signup', 'stage changed'])", universe_filter.key)
        self.assertIn("tuple('signup', '')", universe_filter.key)
        self.assertIn("tuple('stage changed', 'lead')", universe_filter.key)
        self.assertIn("ifNull(toString(properties.stage), '')", universe_filter.key)

        self.assertEqual(funnels_query.dateRange, query.dateRange)
        self.assertEqual(funnels_query.properties, query.properties)
        self.assertEqual(funnels_query.filterTestAccounts, True)

    def test_rejects_item_without_step_source(self):
        query = PathsV2Query(pathsV2Filter=PathsV2Filter(stepSources=_sources("a")))
        with self.assertRaises(ValidationError):
            edge_to_funnels_query(query, self.team, _item("a"), _item("unknown"))
