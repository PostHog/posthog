import re
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
from products.product_analytics.backend.facade.contracts import InsightDashboardContext, InsightSeries
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
                    ("insight:signups", "/dashboard/7", "Growth", 2, TODAY - timedelta(days=1)),
                    ("insight:old", "/insights/old", None, 0, TODAY - timedelta(days=20)),
                ],
            ),
            (
                "a key without dashboard access",
                frozenset({"insight:read"}),
                [("insight:old", "/insights/old", None, 0, TODAY - timedelta(days=20))],
            ),
        ]
    )
    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_the_pulse_shows_a_dashboard_opened_often_as_its_first_working_tile(
        self, _name: str, scopes: frozenset[str] | None, expected: list[tuple[str, str, str | None, int, date]]
    ) -> None:
        for kind, ref, ages in (("insight", "old", (20,)), ("dashboard", "7", (1, 2))):
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
    def test_a_habit_ranks_above_a_more_recent_single_open(self) -> None:
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

        self.assertEqual([m.key for m in pulse], ["insight:habit", "insight:fresh"])

    @parameterized.expand(
        [
            ("first_insight", "a", ["b", "c", "d"]),
            ("dashboard_tile", "slow", ["a", "b", "c", "d"]),
        ]
    )
    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_suggestions_skip_pins_and_keep_fast_results_when_an_earlier_query_uses_the_deadline(
        self, _name: str, slow_ref: str, expected: list[str]
    ) -> None:
        for age, (kind, ref) in enumerate(
            (("insight", "pinned"), ("insight", "a"), ("dashboard", "7"), ("insight", "c"), ("insight", "d")), start=1
        ):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type=kind,
                ref=ref,
                view_days=[TODAY - timedelta(days=age)],
                viewed_at=datetime.combine(TODAY - timedelta(days=age), time(12), tzinfo=UTC),
            )
        growth = DashboardInsights(
            dashboard_id=7,
            name="Growth",
            filters={},
            variables=None,
            tiles=(
                DashboardInsightTile(insight_short_id="slow", filters_overrides=None),
                DashboardInsightTile(insight_short_id="b", filters_overrides=None),
            ),
        )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]
        queried: list[tuple[str, bool, float | None, float]] = []
        started: set[str] = set()
        clock = [0.0]

        def series(**kwargs: Any) -> InsightSeries | None:
            ref = kwargs["short_id"]
            queried.append((ref, kwargs["blocking"], kwargs["wait_until"], clock[0]))
            if ref not in started:
                started.add(ref)
                return None
            if ref == slow_ref and kwargs["blocking"]:
                clock[0] = 30.0
            if ref in ("slow", slow_ref):
                return None
            return insight({"opened": points}, short_id=ref, name=ref)

        with (
            patch.object(routine, "dashboard_insights", return_value=growth),
            patch.object(routine, "get_insight_series", side_effect=series),
            patch.object(routine, "monotonic", side_effect=lambda: clock[0]),
        ):
            pulse = routine.find(
                Context(self.team, self.user, TODAY, pinned=frozenset({"insight:pinned", "signup_event"}))
            ).pulse

        self.assertEqual([metric.key for metric in pulse], [f"insight:{ref}" for ref in expected])
        self.assertEqual({ref for ref, _, _, _ in queried}, {"a", "slow", "b", "c", "d"})
        self.assertTrue(all(deadline == 20.0 for _, _, deadline, _ in queried))
        self.assertTrue(any(blocking for _, blocking, _, _ in queried))
        self.assertTrue(all(not blocking for _, blocking, _, at in queried if at >= 30.0))

    @time_machine.travel("2026-10-13T12:00:00Z", tick=False)
    def test_a_person_with_few_views_also_sees_the_insights_the_project_opens_most(self) -> None:
        others = [User.objects.create_and_join(self.organization, f"viewer{i}@example.com", None) for i in range(2)]
        for user, ref, age in (
            (self.user, "mine", 1),
            (others[0], "mine", 1),
            (others[0], "shared", 1),
            (others[1], "shared", 2),
            (others[1], "once", 1),
            (others[0], "stale", 40),
        ):
            FileSystemViewLog.objects.create(
                team=self.team,
                user=user,
                type="insight",
                ref=ref,
                view_days=[TODAY - timedelta(days=age)],
                viewed_at=datetime.combine(TODAY - timedelta(days=age), time(12), tzinfo=UTC),
            )
        points = [(TODAY - timedelta(days=d), 2.0 if d <= 7 else 1.0) for d in range(14, 0, -1)]

        with patch.object(
            routine,
            "get_insight_series",
            side_effect=lambda **kwargs: insight({"opened": points}, short_id=kwargs["short_id"], name="Opened"),
        ):
            pulse = routine.find(Context(self.team, self.user, TODAY)).pulse

        self.assertEqual(
            [(m.key, m.reason, m.last_opened) for m in pulse],
            [
                ("insight:mine", "routine", TODAY - timedelta(days=1)),
                ("insight:shared", "popular", None),
                ("insight:once", "popular", None),
            ],
        )
