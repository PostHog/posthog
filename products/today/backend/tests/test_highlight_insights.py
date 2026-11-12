import re
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any, cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import FileSystemViewLog, User

from products.dashboards.backend.facade.api import DashboardInsights, DashboardInsightTile
from products.product_analytics.backend.facade.contracts import (
    AgentInsightRead,
    InsightDashboardContext,
    InsightSeries,
    InsightSeriesNotReady,
    SavedInsightDefinition,
)
from products.today.backend.facade.contracts import HighlightFindings, PulseSlot
from products.today.backend.facade.enums import PulseSlotStatus
from products.today.backend.logic.highlight_rules import human, short
from products.today.backend.logic.highlight_trends import BAD_METRIC, MONEY, UNCLEAR_LABEL, UNKNOWN_DIRECTION
from products.today.backend.logic.highlight_types import Context
from products.today.backend.logic.today_highlights import home, routine

TODAY = date(2026, 10, 13)


def days(values: list[float]) -> list[tuple[date, float]]:
    start = TODAY - timedelta(days=len(values))
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def insight(series: dict[str, list[tuple[date, float]]], **fields: Any) -> InsightSeries:
    return InsightSeries(
        **{"short_id": "abc", "name": "By browser", "period": "day", "averaged_series": [], "event_name": "", **fields},
        series=series,
    )


class TestInsightRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("opened today", [TODAY], 1.0),
            ("opened two weeks ago counts half", [TODAY - timedelta(days=14)], 0.5),
            ("each day adds its own weight", [TODAY, TODAY - timedelta(days=14)], 1.5),
            ("a view older than the lookback counts nothing", [TODAY - timedelta(days=91)], 0.0),
            ("a day after today counts nothing", [TODAY + timedelta(days=1)], 0.0),
        ]
    )
    def test_frecency(self, _name: str, view_days: list[date], expected: float) -> None:
        self.assertAlmostEqual(routine.frecency(view_days, TODAY), expected)

    @parameterized.expand(
        [
            (
                "long text cuts at a word with no ellipsis",
                "Cannot read properties of undefined (reading 'earliest')",
                30,
                "Cannot read properties of",
            ),
            (
                "straight quotes become curly",
                "Cannot read properties of null (reading 'price') in user's cart",
                80,
                "Cannot read properties of null (reading ‘price’) in user’s cart",
            ),
        ]
    )
    def test_short(self, _name: str, text: str, limit: int, expected: str) -> None:
        self.assertEqual(short(text, limit), expected)

    @parameterized.expand([(842, "842"), (1240, "1.2k"), (9_960, "10k"), (999_960, "1.0M"), (2_350_000, "2.4M")])
    def test_human_never_prints_a_thousand_of_a_unit(self, value: float, expected: str) -> None:
        self.assertEqual(human(value), expected)


DROP = days([1000.0] * 49 + [550.0] * 7)
ALTERNATING = days([v for week in range(8) for v in [1000.0 if week % 2 == 0 else 800.0] * 7])


class TestHomeTiles(SimpleTestCase):
    @parameterized.expand(
        [
            ("fewer failures is good news", DROP, "payment failed", False, ["Chrome"], None),
            (
                "fewer sign-ups is bad news",
                DROP,
                "signed up",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 45% last week", "7,000 → 3,850"),
            ),
            (
                "daily users compare daily averages",
                DROP,
                "signed up",
                True,
                ["Chrome"],
                ("‘By browser’ decreased by 45% last week", "1,000 → 550 a day on average"),
            ),
            (
                "several series name the series measured",
                DROP,
                "",
                False,
                ["signed up · Chrome", "logged in · Chrome"],
                ("‘By browser’ (signed up · Chrome) decreased by 45% last week", "7,000 → 3,850"),
            ),
            (
                "a drop that no detector flags still counts",
                ALTERNATING,
                "signed up",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 20% last week", "7,000 → 5,600"),
            ),
            (
                "built-in events read as their names",
                DROP,
                "",
                False,
                ["$pageview", "$autocapture"],
                ("‘By browser’ (Pageview) decreased by 45% last week", "7,000 → 3,850"),
            ),
            (
                "net revenue rising toward zero is good news",
                days([-30.0] * 49 + [-20.0] * 7),
                "revenue",
                False,
                ["Chrome"],
                None,
            ),
            (
                "revenue falling below zero is bad news",
                days([30.0] * 49 + [-10.0] * 7),
                "revenue",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 133% last week", "210 → -70"),
            ),
            (
                "small money values keep their cents",
                days([0.2] * 49 + [0.1] * 7),
                "revenue",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 50% last week", "1.40 → 0.70"),
            ),
            (
                "a currency format counts as money",
                days([6.0] * 49 + [3.0] * 7),
                "",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 50% last week", "42 → 21"),
                "currency",
            ),
        ]
    )
    def test_a_home_tile_shows_when_it_moves_the_wrong_way(
        self,
        _name: str,
        points: list[tuple[date, float]],
        event_name: str,
        averaged: bool,
        labels: list[str],
        expected: tuple[str, str] | None,
        value_format: str | None = None,
    ) -> None:
        found_insight = insight(
            {name: [(day, value / (index + 1)) for day, value in points] for index, name in enumerate(labels)},
            averaged_series=labels if averaged else [],
            event_name=event_name,
            value_format=value_format,
        )
        context = cast(
            Context,
            SimpleNamespace(
                team=SimpleNamespace(id=1),
                user=SimpleNamespace(id=2),
                today=TODAY,
                guard=lambda _name, provider, _default: provider(),
            ),
        )
        home_tiles = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(DashboardInsightTile(insight_short_id="abc", filters_overrides=None),),
        )

        with (
            patch.object(home, "home_dashboard_insights", return_value=home_tiles),
            patch.object(home, "get_insight_series", return_value=found_insight),
        ):
            found = home.find(context).items

        self.assertEqual([(c.title, c.detail) for c in found], [expected] if expected else [])

    @parameterized.expand(
        [
            ("$pageview", MONEY, False),
            ("Revenue by plan", MONEY, True),
            ("Spend in $", MONEY, True),
            ("$5 orders", MONEY, True),
            ("Average order value", BAD_METRIC, False),
            ("payment_failed", BAD_METRIC, True),
            ("Rage clicks", BAD_METRIC, True),
            ("Registrations", UNKNOWN_DIRECTION, False),
            ("Conversion ratio", UNKNOWN_DIRECTION, True),
            ("Total revenue", UNCLEAR_LABEL, False),
            ("sum_amount", UNCLEAR_LABEL, True),
            ("Series 2", UNCLEAR_LABEL, True),
        ]
    )
    def test_metric_names_match_whole_terms(self, label: str, pattern: re.Pattern[str], matches: bool) -> None:
        self.assertEqual(bool(pattern.search(label)), matches)

    def test_a_home_link_opens_the_insight_as_the_dashboard_shows_it(self) -> None:
        dashboard = InsightDashboardContext(
            filters={"properties": [{"key": "$browser", "value": "Safari"}]}, tile_filters={"date_from": "-7d"}
        )

        self.assertEqual(
            home._url("abc", 7, dashboard),
            "/insights/abc?dashboard=7"
            "&filters_override=%7B%22properties%22%3A%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%22Safari%22%7D%5D%7D"
            "&tile_filters_override=%7B%22date_from%22%3A%22-7d%22%7D",
        )


class TestRoutineInsights(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.enterContext(
            patch.object(
                routine,
                "viewable_insight_definitions",
                side_effect=lambda short_ids, **_: {
                    short_id: SavedInsightDefinition(
                        id=i,
                        short_id=short_id,
                        name=short_id,
                        query={"kind": "InsightVizNode", "source": {"kind": "TrendsQuery"}},
                    )
                    for i, short_id in enumerate(short_ids)
                },
            )
        )

    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_an_insight_opened_most_days_shows_its_last_week_in_the_pulse(self) -> None:
        FileSystemViewLog.objects.create(
            team=self.team,
            user=self.user,
            type="insight",
            ref="abc",
            view_days=[TODAY - timedelta(days=d) for d in range(10)],
        )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]
        found_insight = insight(
            {"exported_report": points, "$pageview": [(day, value / 2) for day, value in points]},
            name="Files opened",
            value_format="currency",
        )

        with patch.object(routine, "get_insight_series", return_value=found_insight):
            pulse = routine.find(Context(self.team, self.user, TODAY)).pulse

        self.assertEqual(
            [
                (
                    m.name,
                    m.value,
                    m.change_pct,
                    m.interval,
                    m.url,
                    m.value_format and m.value_format.format,
                    m.reason,
                    m.opened_days,
                    m.last_opened,
                    [(mover.label, mover.value, mover.change_pct) for mover in m.movers],
                    m.previous_value,
                )
                for m in pulse
            ],
            [
                (
                    "Files opened (Exported report)",
                    14.0,
                    100.0,
                    "day",
                    "/insights/abc",
                    "currency",
                    "routine",
                    10,
                    TODAY,
                    [("Exported report", 14.0, 100.0), ("Pageview", 7.0, 100.0)],
                    7.0,
                )
            ],
        )

    @parameterized.expand(
        [
            (
                "a session",
                None,
                [
                    ("insight:old", "/insights/old", None, 1, TODAY - timedelta(days=13)),
                    ("insight:signups", "/dashboard/7", "Growth", 3, TODAY - timedelta(days=1)),
                ],
            ),
            (
                "a key without dashboard access",
                frozenset({"insight:read"}),
                [("insight:old", "/insights/old", None, 1, TODAY - timedelta(days=13))],
            ),
        ]
    )
    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_the_pulse_shows_a_dashboard_opened_often_as_its_first_working_tile(
        self, _name: str, scopes: frozenset[str] | None, expected: list[tuple[str, str, str | None, int, date]]
    ) -> None:
        for kind, ref, ages in (("insight", "old", (13, 20, 22)), ("dashboard", "7", (1, 2, 3))):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type=kind,
                ref=ref,
                view_days=[TODAY - timedelta(days=age) for age in ages],
                viewed_at=datetime.combine(TODAY - timedelta(days=min(ages)), time(12), tzinfo=UTC),
            )
        growth = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(
                DashboardInsightTile(insight_short_id="broken", filters_overrides=None),
                DashboardInsightTile(insight_short_id="table", filters_overrides=None),
                DashboardInsightTile(insight_short_id="signups", filters_overrides=None),
            ),
        )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]
        charts = {
            "signups": insight({"signed_up": points}, short_id="signups", name="Sign-ups"),
            "old": insight({"opened": points}, short_id="old", name="Files opened"),
        }

        def series(**kwargs: Any) -> InsightSeries | None:
            if kwargs["short_id"] == "broken":
                raise ValueError("query failed")
            return charts.get(kwargs["short_id"])

        with (
            patch.object(routine, "dashboard_insights", return_value=growth),
            patch.object(routine, "get_insight_series", side_effect=series),
        ):
            pulse = routine.find(Context(self.team, self.user, TODAY, scopes)).pulse

        self.assertEqual([(m.key, m.url, m.dashboard_name, m.opened_days, m.last_opened) for m in pulse], expected)
        self.assertEqual([m.movers for m in pulse], [[]] * len(expected))

    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_a_habit_shows_and_a_more_recent_single_open_does_not(self) -> None:
        for ref, ages in (("habit", range(2, 10)), ("fresh", (1,))):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type="insight",
                ref=ref,
                view_days=[TODAY - timedelta(days=age) for age in ages],
                viewed_at=datetime.combine(TODAY - timedelta(days=min(ages)), time(12), tzinfo=UTC),
            )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]

        with patch.object(
            routine,
            "get_insight_series",
            side_effect=lambda **kwargs: insight({"opened": points}, short_id=kwargs["short_id"], name="Opened"),
        ):
            pulse = routine.find(Context(self.team, self.user, TODAY)).pulse

        self.assertEqual([m.key for m in pulse], ["insight:habit"])

    @parameterized.expand(
        [
            (
                "nothing_hidden",
                frozenset(),
                ["b1", "b2", "b3", "b4"],
                [],
                ["habit", "alerted", "subscribed", "b1", "b2", "b3"],
            ),
            (
                "insights_agents_read_on_two_days_follow_the_habits",
                frozenset(),
                ["b1", "b2", "b3", "b4"],
                [
                    AgentInsightRead("asked", (TODAY - timedelta(days=1), TODAY - timedelta(days=6))),
                    AgentInsightRead("asked_once", (TODAY - timedelta(days=1),)),
                    AgentInsightRead("asked_long_ago", (TODAY - timedelta(days=16), TODAY - timedelta(days=20))),
                ],
                ["habit", "asked", "alerted", "subscribed", "b1", "b2"],
            ),
            (
                "a_hidden_insight_leaves_no_gap",
                frozenset({"insight:alerted"}),
                ["b1", "b2", "b3", "b4"],
                [],
                ["habit", "subscribed", "b1", "b2", "b3", "b4"],
            ),
            (
                "hidden_insights_do_not_use_up_the_candidate_limit",
                frozenset(f"insight:b{index}" for index in range(1, 13)),
                [f"b{index}" for index in range(1, 15)],
                [],
                ["habit", "alerted", "subscribed", "b13", "b14"],
            ),
        ]
    )
    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_the_pulse_mixes_repeated_watched_and_built_insights_without_popular_ones(
        self,
        _name: str,
        hidden: frozenset[str],
        built: list[str],
        asked: list[AgentInsightRead],
        expected: list[str],
    ) -> None:
        other = User.objects.create_and_join(self.organization, "viewer@example.com", None)
        for user, ref, ages in ((self.user, "habit", [1, 5, 9]), (self.user, "once", [1]), (other, "shared", [1])):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=user,
                type="insight",
                ref=ref,
                view_days=[TODAY - timedelta(days=age) for age in ages],
                viewed_at=datetime.combine(TODAY - timedelta(days=min(ages)), time(12), tzinfo=UTC),
            )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]

        with (
            patch.object(
                routine,
                "get_insight_series",
                side_effect=lambda **kwargs: insight({"opened": points}, short_id=kwargs["short_id"], name="Opened"),
            ),
            patch.object(routine, "insight_short_ids_watched_by", return_value=["alerted", "habit"]),
            patch.object(routine, "insight_short_ids_subscribed_by", return_value=["subscribed"]),
            patch.object(routine, "insight_short_ids_built_by", side_effect=lambda **kwargs: built[: kwargs["limit"]]),
            patch.object(routine, "insight_reads_by_agents", return_value=asked),
        ):
            pulse = routine.find(Context(self.team, self.user, TODAY, hidden=hidden)).pulse

        reasons = {"habit": "routine", "alerted": "watched", "subscribed": "watched", "asked": "agent"}
        self.assertEqual(
            [(m.key, m.reason) for m in pulse],
            [(f"insight:{ref}", reasons.get(ref, "built")) for ref in expected],
        )

    @parameterized.expand(
        [
            ("a person without habits", [], ["team_fav", "runner_up", "third"]),
            ("a habit that is already popular", ["team_fav"], ["runner_up", "third"]),
            ("two habits leave two places", ["h1", "h2"], ["team_fav", "runner_up"]),
            ("habits that fill the row", ["h1", "h2", "h3", "h4"], []),
            ("a dashboard habit takes one place", ["dashboard:7"], ["team_fav", "runner_up", "third"]),
            ("a habit without data frees its place", ["h1", "h2", "broken"], ["team_fav", "runner_up"]),
        ]
    )
    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_popular_insights_fill_only_the_places_a_persons_own_habits_leave(
        self, _name: str, habits: list[str], expected: list[str]
    ) -> None:
        viewers = [User.objects.create_and_join(self.organization, f"viewer{i}@example.com", None) for i in range(3)]
        seen = {
            "team_fav": viewers,
            "broken": viewers,
            "runner_up": viewers[:2],
            "third": viewers[:2],
            "solo": viewers[:1],
            "ignored": viewers,
        }
        for ref, people in seen.items():
            for person in people:
                FileSystemViewLog.objects.create(
                    team=self.team,
                    user=person,
                    type="insight",
                    ref=ref,
                    viewed_at=datetime.combine(TODAY - timedelta(days=2), time(12), tzinfo=UTC),
                )
        for habit in habits:
            kind, _, ref = habit.rpartition(":")
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type=kind or "insight",
                ref=ref,
                view_days=[TODAY - timedelta(days=age) for age in (1, 5, 9)],
                viewed_at=datetime.combine(TODAY - timedelta(days=1), time(12), tzinfo=UTC),
            )
        growth = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=tuple(DashboardInsightTile(insight_short_id=f"g{i}", filters_overrides=None) for i in range(4)),
        )
        points = [(TODAY - timedelta(days=d), 2.0) for d in range(14, 0, -1)]

        def series(**kwargs: Any) -> InsightSeries | None:
            if kwargs["short_id"] == "broken":
                return None
            return insight({"opened": points}, short_id=kwargs["short_id"], name="Opened")

        with (
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(routine, "dashboard_insights", return_value=growth),
        ):
            pulse = routine.find(Context(self.team, self.user, TODAY, hidden=frozenset({"insight:ignored"}))).pulse

        self.assertEqual([m.key for m in pulse if m.reason == "popular"], [f"insight:{ref}" for ref in expected])


class TestProgressiveInsights(SimpleTestCase):
    def test_ready_numbers_are_published_while_the_first_query_is_still_running(self) -> None:
        clock = [0.0]
        published: list[tuple[float, HighlightFindings, list[PulseSlot]]] = []
        ready_at = {"slow": 30.0, "fast": 1.0, "empty": 0.0, "timeout": 200.0, "spare": 2.0}
        views = [routine.ViewedItem(kind="insight", ref=ref, days=frozenset({TODAY})) for ref in ready_at]
        definitions = {
            ref: SavedInsightDefinition(id=i, short_id=ref, name=ref, query={"kind": "TrendsQuery"})
            for i, ref in enumerate(ready_at)
        }
        queried: list[tuple[str, float]] = []

        def advance(seconds: float) -> None:
            clock[0] += seconds

        def series(**kwargs: Any) -> InsightSeries | None:
            ref = kwargs["short_id"]
            queried.append((ref, clock[0]))
            self.assertFalse(kwargs["blocking"])
            self.assertTrue(kwargs["raise_on_pending"])
            if clock[0] < ready_at[ref]:
                raise InsightSeriesNotReady(ref)
            return insight({"opened": days([10.0] * 56)}, short_id=ref, name=ref) if ref != "empty" else None

        context = cast(
            Context,
            SimpleNamespace(
                team=None,
                user=None,
                today=TODAY,
                failures=[],
                guard=lambda name, compute, fallback: compute(),
                publish_pulse=lambda found, slots: published.append((clock[0], found, slots)),
            ),
        )
        with (
            patch.object(routine, "viewable_insight_definitions", return_value=definitions),
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(
                routine, "insight_query_complete", side_effect=lambda **kwargs: clock[0] >= ready_at[kwargs["query_id"]]
            ),
            patch.object(routine, "monotonic", side_effect=lambda: clock[0]),
            patch.object(routine, "sleep", side_effect=advance),
        ):
            found = routine.progressive_metrics(context, frozenset(), 4, views)

        self.assertEqual(published[0][0], 0)
        self.assertEqual([slot.key for slot in published[0][2]], [f"insight:{ref}" for ref in list(ready_at)[:4]])
        self.assertTrue(all(slot.status == PulseSlotStatus.PENDING for slot in published[0][2]))
        first_number = next((at, result) for at, result, _ in published if result.pulse)
        self.assertEqual(first_number[0], 1.0)
        self.assertEqual(first_number[1].pulse[0].key, "insight:fast")
        self.assertEqual([metric.key for metric in found], ["insight:slow", "insight:fast", "insight:spare"])
        self.assertEqual(clock[0], routine.BLOCKING_SECONDS)
        self.assertEqual({ref for ref, at in queried if at == 0}, {"slow", "fast", "empty", "timeout"})
        self.assertEqual(
            {slot.key: slot.status for slot in published[-1][2]},
            {
                "insight:slow": PulseSlotStatus.READY,
                "insight:fast": PulseSlotStatus.READY,
                "insight:empty": PulseSlotStatus.EMPTY,
                "insight:timeout": PulseSlotStatus.ERROR,
                "insight:spare": PulseSlotStatus.READY,
            },
        )
        self.assertEqual(context.failures, ["insight:timeout"])
        self.assertEqual(
            Counter(ref for ref, _ in queried), {"slow": 2, "fast": 2, "empty": 1, "timeout": 1, "spare": 2}
        )

    def test_failed_candidates_are_replaced_and_only_transient_errors_mark_the_source_failed(self) -> None:
        dashboard = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(
                DashboardInsightTile(insight_short_id="a", filters_overrides=None),
                DashboardInsightTile(insight_short_id="b", filters_overrides=None),
            ),
        )
        views = [
            routine.ViewedItem(kind="dashboard", ref="7", days=frozenset({TODAY})),
            *(routine.ViewedItem(kind="insight", ref=ref, days=frozenset({TODAY})) for ref in ("broken", "bad", "b")),
        ]
        definitions = {
            ref: SavedInsightDefinition(id=i, short_id=ref, name=ref, query={"kind": "TrendsQuery"})
            for i, ref in enumerate(("a", "b", "broken", "bad"))
        }
        errors: dict[str, Exception] = {"broken": ConnectionError("network"), "bad": ValueError("Insight query failed")}

        def series(**kwargs: Any) -> InsightSeries:
            ref = kwargs["short_id"]
            if ref in errors:
                raise errors[ref]
            return insight({"opened": days([10.0] * 56)}, short_id=ref, name=ref)

        context = cast(
            Context,
            SimpleNamespace(
                team=None,
                user=None,
                today=TODAY,
                failures=[],
                guard=lambda name, compute, fallback: compute(),
                publish_pulse=lambda found, slots: None,
            ),
        )
        with (
            patch.object(routine, "dashboard_insights", return_value=dashboard),
            patch.object(routine, "viewable_insight_definitions", return_value=definitions),
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(routine, "capture_exception"),
        ):
            found = routine.progressive_metrics(context, frozenset(), 2, views)

        self.assertEqual(
            [(metric.key, metric.dashboard_id) for metric in found], [("insight:a", 7), ("insight:b", None)]
        )
        self.assertEqual(context.failures, ["insight:broken"])

    def test_a_dashboard_skips_an_unsupported_tile_before_selecting_a_loading_card(self) -> None:
        viewed = routine.ViewedItem(kind="dashboard", ref="7", days=frozenset({TODAY}))
        dashboard = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(
                DashboardInsightTile(insight_short_id="number", filters_overrides=None),
                DashboardInsightTile(insight_short_id="chart", filters_overrides=None),
            ),
        )
        definitions = {
            ref: SavedInsightDefinition(
                id=i,
                short_id=ref,
                name=ref,
                query={
                    "kind": "InsightVizNode",
                    "source": {
                        "kind": "TrendsQuery",
                        "series": [{"kind": "EventsNode", "event": "opened"}],
                        "trendsFilter": {"display": display},
                    },
                },
            )
            for i, (ref, display) in enumerate([("number", "BoldNumber"), ("chart", "ActionsLineGraph")])
        }
        published: list[list[PulseSlot]] = []
        context = cast(
            Context,
            SimpleNamespace(
                team=None,
                user=None,
                today=TODAY,
                failures=[],
                guard=lambda name, compute, fallback: compute(),
                publish_pulse=lambda found, slots: published.append(slots),
            ),
        )
        with (
            patch.object(routine, "dashboard_insights", return_value=dashboard),
            patch.object(routine, "viewable_insight_definitions", return_value=definitions),
            patch.object(
                routine, "get_insight_series", return_value=insight({"opened": days([10.0] * 56)}, short_id="chart")
            ) as query,
        ):
            found = routine.progressive_metrics(context, frozenset(), 6, [viewed])
        self.assertEqual([slot.key for slot in published[0]], ["insight:chart"])
        self.assertEqual([metric.key for metric in found], ["insight:chart"])
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs["short_id"], "chart")
