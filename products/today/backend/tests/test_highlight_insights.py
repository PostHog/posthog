from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, cast

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import FileSystemViewLog

from products.dashboards.backend.facade.api import HomeDashboardInsights
from products.product_analytics.backend.facade.contracts import InsightSeries
from products.today.backend.logic.highlight_registry import load_sources
from products.today.backend.logic.highlight_rules import human, short
from products.today.backend.logic.highlight_sources import home, routine
from products.today.backend.logic.highlight_types import Context

TODAY = date(2026, 10, 13)


def days(values: list[float]) -> list[tuple[date, float]]:
    start = TODAY - timedelta(days=len(values))
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def insight(series: dict[str, list[tuple[date, float]]], **fields: Any) -> InsightSeries:
    return InsightSeries(
        **{"short_id": "abc", "name": "By browser", "period": "day", "averaged": False, "event_name": "", **fields},
        series=series,
    )


class TestInsightRules(SimpleTestCase):
    @parameterized.expand(
        [
            ("opened on most days", [TODAY - timedelta(days=d) for d in range(10)], 10),
            ("opened every Monday", [TODAY - timedelta(days=1 + 7 * w) for w in range(4)], 4),
            ("opened on many days of one week", [TODAY - timedelta(days=d) for d in range(5)], 0),
            ("a habit that stopped a month ago", [TODAY - timedelta(days=30 + 7 * w) for w in range(4)], 0),
        ]
    )
    def test_routine_days(self, _name: str, view_days: list[date], expected: int) -> None:
        self.assertEqual(routine.routine_days(view_days, TODAY), expected)

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


class TestHomeTiles(SimpleTestCase):
    @parameterized.expand(
        [
            ("fewer failures is good news", "payment failed", False, ["Chrome"], None),
            (
                "fewer sign-ups is bad news",
                "signed up",
                False,
                ["Chrome"],
                ("‘By browser’ decreased by 45% last week", "7,000 → 3,850"),
            ),
            (
                "daily users compare daily averages",
                "signed up",
                True,
                ["Chrome"],
                ("‘By browser’ decreased by 45% last week", "1,000 → 550 a day on average"),
            ),
            (
                "several series name the series measured",
                "",
                False,
                ["signed up · Chrome", "logged in · Chrome"],
                ("‘By browser’ (signed up · Chrome) decreased by 45% last week", "7,000 → 3,850"),
            ),
        ]
    )
    def test_a_home_tile_shows_when_it_moves_the_wrong_way(
        self, _name: str, event_name: str, averaged: bool, labels: list[str], expected: tuple[str, str] | None
    ) -> None:
        points = days([1000.0] * 49 + [550.0] * 7)
        found_insight = insight(
            {name: [(day, value / (index + 1)) for day, value in points] for index, name in enumerate(labels)},
            averaged=averaged,
            event_name=event_name,
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
        registered = next(s for s in load_sources() if s.name == "home")

        with (
            patch.object(
                home,
                "home_dashboard_insights",
                return_value=HomeDashboardInsights(dashboard_id=1, filters={}, insight_short_ids=("abc",)),
            ),
            patch.object(home, "get_insight_series", return_value=found_insight),
        ):
            found = registered.find(context).items

        self.assertEqual([(c.title, c.detail) for c in found], [expected] if expected else [])


class TestRoutineInsights(BaseTest):
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
        found_insight = insight({"exported_report": points}, name="Files opened", value_format="currency")
        registered = next(s for s in load_sources() if s.name == "routine")

        with (
            patch.object(routine, "get_insight_series", return_value=found_insight),
        ):
            pulse = registered.find(Context(self.team, self.user, TODAY)).pulse

        self.assertEqual(
            [
                (m.name, m.value, m.change_pct, m.interval, m.url, m.value_format and m.value_format.format)
                for m in pulse
            ],
            [("Files opened", 14.0, 100.0, "day", "/insights/abc", "currency")],
        )
