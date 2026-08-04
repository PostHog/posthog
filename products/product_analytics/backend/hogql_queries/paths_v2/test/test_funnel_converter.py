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

# Each case pins the edge contract for one journey shape via two assertions on shared fixtures:
# - the converted funnel reproduces the hand-derived POSITION-FREE count: unique actors with any
#   untrimmed journey where the target is the next included path item after the source;
# - the runner's displayed edges stay POSITIONAL: one (stepIndex, count) row per step at which
#   the pair occurs.
# Where the pair occurs at exactly one step the two numbers coincide; multi_step_pair and
# trim_skew are the cases where they deliberately differ.
# Tuple shape: (name, events_by_person, filter_overrides, source, target,
#               expected position-free funnel count, expected positional edge rows).
EDGE_CONTRACT_CASES: list[
    tuple[str, dict[str, Any], dict[str, Any], PathsV2Item, PathsV2Item, int, list[tuple[int, int]]]
] = [
    (
        "simple_edge",
        # p1 and p2 each have b as the next item after a; p3 goes to c instead.
        {"p1": _timeline("a", "b"), "p2": _timeline("a", "b"), "p3": _timeline("a", "c")},
        {},
        _item("a"),
        _item("b"),
        2,
        [(0, 2)],
    ),
    (
        "loop_revisit",
        # b is followed by a once, at the journey's second position only.
        {"p1": _timeline("a", "b", "a", "b")},
        {},
        _item("b"),
        _item("a"),
        1,
        [(1, 1)],
    ),
    (
        "collapse_on_repeated_source",
        # The repeated a re-anchors the funnel exactly like collapse merges the repeat.
        {"p1": _timeline("a", "a", "b")},
        {},
        _item("a"),
        _item("b"),
        1,
        [(0, 1)],
    ),
    (
        "collapse_off_self_edge",
        # p2's intervening c breaks the self-edge on both sides.
        {"p1": _timeline("a", "a", "b"), "p2": _timeline("a", "c", "a")},
        {"collapseRepeats": False},
        _item("a"),
        _item("a"),
        1,
        [(0, 1)],
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
        _item("a"),
        _item("b"),
        1,
        [(0, 1)],
    ),
    (
        "intervening_included_item",
        # p2's c is an included path item between a and b, so the edge and the funnel's
        # item-strict exclusion must both drop p2.
        {"p1": _timeline("a", "b"), "p2": _timeline("a", "c", "b")},
        {},
        _item("a"),
        _item("b"),
        1,
        [(0, 1)],
    ),
    (
        "exclusion_reanchors",
        # After the intervening c, the second a re-anchors: the edge exists (at the third
        # position) and the funnel must count the actor rather than dropping them for the
        # earlier exclusion.
        {"p1": _timeline("a", "c", "a", "b")},
        {},
        _item("a"),
        _item("b"),
        1,
        [(2, 1)],
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
        _item("a"),
        _item("b"),
        1,
        [(0, 1)],
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
        _item("b"),
        _item("c"),
        1,
        [(0, 1)],
    ),
    (
        "multi_step_pair",
        # a is followed by b at step 0 for p1 and at step 1 for p2: the displayed grid keeps one
        # positional row per step (1 actor each), while the position-free funnel counts the
        # union of both actor sets.
        {"p1": _timeline("a", "b"), "p2": _timeline("c", "a", "b")},
        {},
        _item("a"),
        _item("b"),
        2,
        [(0, 1), (1, 1)],
    ),
    (
        "trim_skew",
        # p1's only a-to-b adjacency sits beyond the maxSteps trim, so no a-to-b edge is
        # displayed at all; the funnel still counts the actor because the contract is over
        # untrimmed journeys and the trim is display-only.
        {"p1": _timeline("x", "y", "a", "b")},
        {"maxSteps": 2, "stepSources": _sources("x", "y", "a", "b")},
        _item("a"),
        _item("b"),
        1,
        [],
    ),
]


class TestPathsV2EdgeContract(ClickhouseTestMixin, APIBaseTest):
    maxDiff = None

    def _edge_rows(self, query: PathsV2Query, source: PathsV2Item, target: PathsV2Item) -> list[tuple[int, float]]:
        results = PathsV2QueryRunner(query=query, team=self.team).calculate().results
        return [
            (edge.stepIndex, edge.count) for edge in results.edges if edge.source == source and edge.target == target
        ]

    def _funnel_count(self, query: PathsV2Query, source: PathsV2Item, target: PathsV2Item) -> float:
        funnels_query = edge_to_funnels_query(query, self.team, source, target)
        results = FunnelsQueryRunner(query=funnels_query, team=self.team).calculate().results
        return results[1]["count"]

    @parameterized.expand(EDGE_CONTRACT_CASES)
    def test_funnel_counts_position_free_pairs(
        self,
        _name: str,
        events_by_person: dict[str, list[dict[str, Any]]],
        filter_overrides: dict[str, Any],
        source: PathsV2Item,
        target: PathsV2Item,
        expected_funnel_count: int,
        expected_edge_rows: list[tuple[int, int]],
    ):
        journeys_for(team=self.team, events_by_person=events_by_person)
        query = PathsV2Query(
            dateRange=DATE_RANGE,
            pathsV2Filter=PathsV2Filter(**{"stepSources": SIMPLE_SOURCES, **filter_overrides}),
        )

        self.assertEqual(self._funnel_count(query, source, target), expected_funnel_count)
        self.assertEqual(self._edge_rows(query, source, target), expected_edge_rows)

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
        self.assertEqual(self._funnel_count(query, source, target), 1)
        self.assertEqual(self._edge_rows(query, source, target), [(0, 1)])

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
        self.assertEqual(self._funnel_count(query, source, target), 2)
        self.assertEqual(self._edge_rows(query, source, target), [(0, 2)])

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

        self.assertEqual(self._funnel_count(query, source, target), 1)
        self.assertEqual(self._edge_rows(query, source, target), [(0, 1)])

    def test_month_gap_uses_fixed_31_days_in_both_engines(self):
        journeys_for(
            team=self.team,
            events_by_person={
                # 30-day gap: within the fixed 31-day month but beyond the calendar month
                # (Feb 1 plus one month is Mar 1), so calendar INTERVAL arithmetic on either
                # side would split the journey or fail the conversion.
                "p1": [
                    {"event": "a", "timestamp": "2025-02-01 10:00:00"},
                    {"event": "b", "timestamp": "2025-03-03 10:00:00"},
                ],
                # 32-day gap: beyond the fixed 31 days, so both engines must drop it.
                "p2": [
                    {"event": "a", "timestamp": "2025-02-01 10:00:00"},
                    {"event": "b", "timestamp": "2025-03-05 10:00:00"},
                ],
            },
        )
        query = PathsV2Query(
            dateRange=DateRange(date_from="2025-02-01", date_to="2025-03-31"),
            pathsV2Filter=PathsV2Filter(
                stepSources=SIMPLE_SOURCES,
                gapInterval=1,
                gapIntervalUnit=FunnelConversionWindowTimeUnit.MONTH,
            ),
        )
        source, target = _item("a"), _item("b")

        # Both engines realize a one-month gap as DATERANGE_MAP's fixed 31 days
        # (conversion_window_to_seconds), never as calendar months.
        self.assertEqual(self._funnel_count(query, source, target), 1)
        self.assertEqual(self._edge_rows(query, source, target), [(0, 1)])


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
