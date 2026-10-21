from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import partial
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from pydantic import TypeAdapter

from posthog.constants import AvailableFeature
from posthog.models import Team, User

from products.access_control.backend.facade.testing import create_access_control
from products.today.backend.facade import contracts
from products.today.backend.facade.contracts import (
    HighlightCandidate,
    HighlightContext,
    HighlightFindings,
    HighlightSource,
)
from products.today.backend.facade.enums import (
    HighlightInterval,
    HighlightLabel,
    HighlightPriority,
    HighlightsStatus,
    HighlightUnit,
)
from products.today.backend.logic import highlight_registry, highlight_types, highlights
from products.today.backend.logic.highlight_types import Context
from products.today.backend.logic.highlights import MAX_ITEMS, rank
from products.today.backend.models import TodayHighlights
from products.today.backend.temporal.inputs import (
    FinalizeHighlightsInputs,
    HighlightSourceInputs,
    HighlightSourceResult,
)

DAY = date(2026, 10, 13)
FOUND = TypeAdapter(HighlightFindings)
HIGHLIGHTS = TypeAdapter(contracts.Highlights)


def candidate(
    key: str, family: str, importance: float, title: str | None = None, ref: str | None = None
) -> HighlightCandidate:
    return HighlightCandidate(
        key=key,
        label=HighlightLabel.RISK,
        family=family,
        importance=importance,
        relevance=1.0,
        title=title or key,
        detail="",
        ref=ref,
    )


def metric(key: str) -> contracts.HighlightMetric:
    return contracts.HighlightMetric(
        key=key, name=key, value=1.0, unit=HighlightUnit.EVENTS, change_pct=None, series=[1.0]
    )


ALERT_RESULT = HighlightSourceResult(
    source_name="alerts",
    found=FOUND.dump_json(HighlightFindings(items=(candidate("alert", "alerts", 0.8),))).decode(),
    failed=False,
)
FAILED_RESULT = HighlightSourceResult(source_name="errors", found=None, failed=True)
PARTIAL_RESULT = HighlightSourceResult(source_name="alerts", found=ALERT_RESULT.found, failed=True)
READY_CONTENT = HIGHLIGHTS.dump_python(
    contracts.Highlights(
        status=HighlightsStatus.READY,
        generated_at=datetime(2026, 10, 13, 11, 0, tzinfo=UTC),
        day=DAY,
        refresh_at=datetime(2026, 10, 14, tzinfo=UTC),
        pulse=[metric("k1")],
        items=[],
    ),
    mode="json",
)


class TestHighlightRanking(SimpleTestCase):
    def test_one_family_cannot_fill_the_list(self) -> None:
        ranked = rank([candidate(f"flag {i}", "flags", 0.9) for i in range(5)] + [candidate("alert", "alerts", 0.5)])
        self.assertEqual([c.family for c in ranked], ["flags", "flags", "alerts"])

    def test_the_list_keeps_the_highest_scores_and_drops_weak_items(self) -> None:
        candidates = [candidate(f"item {i}", f"family {i}", 0.9 - i * 0.05) for i in range(8)]
        candidates.append(candidate("weak", "weak", 0.1))
        ranked = rank(candidates)
        self.assertEqual(len(ranked), MAX_ITEMS)
        self.assertEqual([c.key for c in ranked], [f"item {i}" for i in range(MAX_ITEMS)])

    @parameterized.expand(
        [
            ("title", {"title": "Postgres sync failed once in the last 7 days"}),
            ("reference", {"ref": "insight-abc"}),
        ]
    )
    def test_a_repeated_title_or_reference_is_dropped_only_across_families(
        self, _name: str, shared: dict[str, str]
    ) -> None:
        ranked = rank(
            [
                candidate("first", "alerts", 0.75, **shared),
                candidate("second", "alerts", 0.74, **shared),
                candidate("other area", "home", 0.7, **shared),
            ]
        )
        self.assertEqual([c.key for c in ranked], ["first", "second"])

    @parameterized.expand(
        [
            ("urgent risk", HighlightLabel.RISK, 0.75, HighlightPriority.P1),
            ("risk", HighlightLabel.RISK, 0.749, HighlightPriority.P2),
            ("opportunity", HighlightLabel.OPPORTUNITY, 0.4, HighlightPriority.P3),
            ("minor opportunity", HighlightLabel.OPPORTUNITY, 0.399, HighlightPriority.P4),
        ]
    )
    def test_priority_follows_the_label_and_the_score(
        self, _name: str, label: HighlightLabel, score: float, expected: HighlightPriority
    ) -> None:
        self.assertEqual(highlights.priority(label, score), expected)


class TestBuildHighlights(SimpleTestCase):
    def test_the_pulse_follows_the_source_order_and_the_items_follow_priority(self) -> None:
        sources = (
            HighlightSource(name="key_metrics", find=lambda _c: HighlightFindings(), pulse_order=2),
            HighlightSource(name="routine", find=lambda _c: HighlightFindings(), pulse_order=1),
            HighlightSource(name="experiments", find=lambda _c: HighlightFindings()),
            HighlightSource(name="alerts", find=lambda _c: HighlightFindings()),
        )
        found = {
            "key_metrics": HighlightFindings(pulse=(metric("k1"), metric("k2"), metric("k3"))),
            "routine": HighlightFindings(pulse=(metric("r1"), metric("r2"))),
            "experiments": HighlightFindings(
                items=(replace(candidate("win", "experiments", 0.9), label=HighlightLabel.OPPORTUNITY),)
            ),
            "alerts": HighlightFindings(items=(candidate("alert", "alerts", 0.5),)),
        }

        built = highlights.build_highlights(sources, found, Team(timezone="Europe/Prague"), DAY)

        self.assertEqual(
            (
                [m.key for m in built.pulse],
                [(i.key, i.source, i.priority) for i in built.items],
                built.day,
                built.refresh_at,
            ),
            (
                ["r1", "r2", "k1", "k2"],
                [("alert", "alerts", HighlightPriority.P2), ("win", "experiments", HighlightPriority.P3)],
                DAY,
                datetime(2026, 10, 14, tzinfo=ZoneInfo("Europe/Prague")),
            ),
        )

    def test_pins_lead_the_pulse_and_each_pin_reports_its_state(self) -> None:
        source = HighlightSource(name="metrics", find=lambda _c: HighlightFindings())

        built = highlights.build_highlights(
            (source,),
            {"metrics": HighlightFindings(pulse=(metric("offered"), metric("suggested")))},
            Team(timezone="UTC"),
            DAY,
            pins=["insight:pinned", "offered", "insight:slow", "insight:gone"],
            pinned={"insight:pinned": metric("insight:pinned")},
        )

        self.assertEqual(
            ([m.key for m in built.pulse], [(pin.key, pin.status) for pin in built.pins]),
            (
                ["insight:pinned", "offered", "suggested"],
                [
                    ("insight:pinned", "ready"),
                    ("offered", "ready"),
                    ("insight:slow", "unavailable"),
                    ("insight:gone", "unavailable"),
                ],
            ),
        )

    @parameterized.expand(
        [
            ("days", HighlightInterval.DAY, None, 3, [date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)]),
            ("weeks from Sunday", HighlightInterval.WEEK, None, 2, [date(2026, 9, 27), date(2026, 10, 4)]),
            ("weeks from Monday", HighlightInterval.WEEK, 1, 2, [date(2026, 9, 28), date(2026, 10, 5)]),
            ("months", HighlightInterval.MONTH, None, 2, [date(2026, 8, 1), date(2026, 9, 1)]),
        ]
    )
    def test_each_pulse_value_gets_the_start_of_its_complete_period(
        self, _name: str, interval: HighlightInterval, week_start_day: int | None, count: int, expected: list[date]
    ) -> None:
        tile = replace(metric("k"), series=[1.0] * count, interval=interval)
        source = HighlightSource(name="metrics", find=lambda _c: HighlightFindings())

        built = highlights.build_highlights(
            (source,), {"metrics": HighlightFindings(pulse=(tile,))}, Team(week_start_day=week_start_day), DAY
        )

        self.assertEqual(built.pulse[0].period_starts, expected)


class TestRunSource(BaseTest):
    def _run(
        self, source: HighlightSource, user: User | None = None, scopes: list[str] | None = None
    ) -> HighlightSourceResult:
        inputs = HighlightSourceInputs(
            team_id=self.team.id,
            user_id=(user or self.user).id,
            local_day=DAY.isoformat(),
            scopes=scopes,
            source_name=source.name,
        )
        with patch.object(highlights, "load_sources", return_value=(source,)):
            return highlights.run_source(inputs)

    @parameterized.expand(
        [
            ("a session", None, True),
            ("a key without the scope", ["query:read", "today:read"], False),
            ("a key with the write scope", ["alert:write"], True),
            ("a key with every scope", ["*"], True),
        ]
    )
    def test_a_source_runs_only_when_the_credential_covers_its_scopes(
        self, _name: str, scopes: list[str] | None, runs: bool
    ) -> None:
        source = HighlightSource(
            name="alerts",
            find=lambda _c: HighlightFindings(items=(candidate("alert", "alerts", 0.8),)),
            scopes=("alert:read",),
        )

        result = self._run(source, scopes=scopes)

        self.assertEqual((result.found is not None, result.failed), (runs, False))

    @parameterized.expand(
        [
            ("no rule", "error_tracking", None, True),
            ("viewer", "error_tracking", "viewer", True),
            ("no access", "error_tracking", "none", False),
            ("no access to the parent of a child resource", "warehouse_objects", "none", False),
        ]
    )
    def test_a_source_runs_only_when_the_person_can_view_its_resource(
        self, _name: str, resource: str, access_level: str | None, runs: bool
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        if access_level:
            create_access_control(team_id=self.team.id, resource=resource, access_level=access_level)
        source = HighlightSource(
            name="errors",
            find=lambda _c: HighlightFindings(items=(candidate("error", "errors", 0.8),)),
            scopes=("warehouse_view:read",) if resource == "warehouse_objects" else ("error_tracking:read",),
        )

        result = self._run(source, user=self._create_user("reader@example.com"))

        self.assertEqual(result.found is not None, runs)

    def test_a_broken_source_reports_a_failure_instead_of_raising(self) -> None:
        def broken(_context: HighlightContext) -> HighlightFindings:
            raise ValueError("boom")

        result = self._run(HighlightSource(name="broken", find=broken))

        self.assertEqual((result.failed, FOUND.validate_json(result.found or "")), (True, HighlightFindings()))


class TestFinalizeHighlights(BaseTest):
    @parameterized.expand(
        [
            ("one source failed", [ALERT_RESULT, FAILED_RESULT], HighlightsStatus.READY, ["alert"], False),
            ("every source failed", [FAILED_RESULT], HighlightsStatus.FAILED, [], True),
            ("every source failed but one kept an item", [PARTIAL_RESULT], HighlightsStatus.READY, ["alert"], False),
        ]
    )
    def test_a_ready_computation_replaces_the_older_rows(
        self,
        _name: str,
        results: list[HighlightSourceResult],
        status: HighlightsStatus,
        items: list[str],
        keeps_older: bool,
    ) -> None:
        rows = TodayHighlights.objects.for_team(self.team.id)
        older = rows.create(team_id=self.team.id, user_id=self.user.id, local_day=DAY, key="k")
        rows.filter(id=older.id).update(created_at=older.created_at - timedelta(minutes=20))
        computing = rows.create(team_id=self.team.id, user_id=self.user.id, local_day=DAY, key="k")

        highlights.finalize(
            FinalizeHighlightsInputs(team_id=self.team.id, highlights_id=str(computing.id), results=results)
        )

        computing.refresh_from_db()
        content = HIGHLIGHTS.validate_python(computing.content)
        self.assertEqual(
            (
                computing.status,
                computing.failed_sources,
                [i.key for i in content.items],
                rows.filter(id=older.id).exists(),
            ),
            (status, True, items, keeps_older),
        )


@time_machine.travel(datetime(2026, 10, 13, 12, 0, tzinfo=UTC), tick=False)
class TestGetHighlights(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    @parameterized.expand(
        [
            ("nothing yet", None, HighlightsStatus.COMPUTING, 1, []),
            (
                "a fresh ready row",
                {"status": HighlightsStatus.READY, "ready_at": timedelta(minutes=1)},
                HighlightsStatus.READY,
                0,
                ["k1"],
            ),
            (
                "a computing row inside the retry budget",
                {"created_at": timedelta(minutes=3)},
                HighlightsStatus.COMPUTING,
                0,
                [],
            ),
            ("a lost computing row", {"created_at": timedelta(minutes=6)}, HighlightsStatus.COMPUTING, 1, []),
            (
                "a stale ready row",
                {"status": HighlightsStatus.READY, "ready_at": timedelta(minutes=20)},
                HighlightsStatus.COMPUTING,
                1,
                ["k1"],
            ),
            (
                "a ready row with a failed source",
                {"status": HighlightsStatus.READY, "ready_at": timedelta(minutes=2), "failed_sources": True},
                HighlightsStatus.COMPUTING,
                1,
                ["k1"],
            ),
            (
                "a fresh failure",
                {"status": HighlightsStatus.FAILED, "ready_at": timedelta(seconds=30), "failed_sources": True},
                HighlightsStatus.FAILED,
                0,
                [],
            ),
            (
                "a ready row from yesterday",
                {"status": HighlightsStatus.READY, "ready_at": timedelta(minutes=1), "local_day": date(2026, 10, 12)},
                HighlightsStatus.COMPUTING,
                1,
                [],
            ),
            (
                "a ready row for the other pulse ranking",
                {"status": HighlightsStatus.READY, "ready_at": timedelta(minutes=1)},
                HighlightsStatus.COMPUTING,
                1,
                [],
                "frecency",
            ),
        ]
    )
    def test_the_request_never_waits_for_a_computation(
        self,
        _name: str,
        row: dict[str, Any] | None,
        status: HighlightsStatus,
        starts: int,
        pulse: list[str],
        ranking_later: str = "control",
    ) -> None:
        connect = MagicMock()
        connect.return_value.start_workflow = AsyncMock()
        ranking = ["control"]
        with (
            patch.object(highlights, "sync_connect", connect),
            patch.object(highlights, "pulse_ranking", side_effect=lambda _user, _team: ranking[0]),
        ):
            if row is not None:
                highlights.get_highlights(team=self.team, user=self.user, scopes=None)
                now = timezone.now()
                TodayHighlights.objects.for_team(self.team.id).update(
                    content=READY_CONTENT,
                    **{name: now - value if isinstance(value, timedelta) else value for name, value in row.items()},
                )
                connect.return_value.start_workflow.reset_mock()
                cache.clear()
                ranking[0] = ranking_later
            found = highlights.get_highlights(team=self.team, user=self.user, scopes=None)

        self.assertEqual(
            (found.status, connect.return_value.start_workflow.call_count, [m.key for m in found.pulse]),
            (status, starts, pulse),
        )


class TestDailyCache(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()

    def _context(self) -> Context:
        return Context(self.team, self.user, date(2026, 10, 13))

    @parameterized.expand([("a value", False, 1), ("an error", True, 2)])
    def test_a_daily_value_is_computed_once_unless_computing_it_raises(
        self, _name: str, fails: bool, computes: int
    ) -> None:
        calls: list[int] = []

        def compute() -> int:
            calls.append(1)
            if fails:
                raise ValueError("boom")
            return 7

        for context in (self._context(), self._context()):
            context.guard("value", partial(context.daily, "value", compute), 0)

        self.assertEqual(len(calls), computes)

    def test_a_request_skips_a_daily_value_another_request_is_computing(self) -> None:
        context = self._context()
        key = f"today_highlights:daily:v1:{self.team.id}:{context.restrictions}:2026-10-13:value"
        cache.add(f"{key}:lock", True, 60)
        calls: list[int] = []

        def compute() -> int:
            calls.append(1)
            return 7

        with patch.object(highlight_types, "capture_exception") as captured:
            found = context.guard("value", lambda: context.daily("value", compute), 0)

        self.assertEqual((found, calls, context.failures, captured.call_count), (0, [], ["value"], 0))


def declaring(*sources: object) -> SimpleNamespace:
    return SimpleNamespace(__name__="products.example.backend.facade.today_highlights", HIGHLIGHT_SOURCES=sources)


def declaring_one(source: object) -> SimpleNamespace:
    return SimpleNamespace(__name__="products.example.backend.facade.today_highlights", HIGHLIGHT_SOURCES=source)


class TestLoadSources(SimpleTestCase):
    @parameterized.expand(
        [
            ("no declaration", SimpleNamespace(__name__="products.example.backend.facade.today_highlights")),
            (
                "a single source without a tuple",
                declaring_one(HighlightSource(name="alerts", find=lambda _c: HighlightFindings())),
            ),
            ("not a source", declaring("alerts")),
            ("an empty name", declaring(HighlightSource(name="", find=lambda _c: HighlightFindings()))),
            (
                "a name taken twice",
                declaring(
                    HighlightSource(name="alerts", find=lambda _c: HighlightFindings()),
                    HighlightSource(name="alerts", find=lambda _c: HighlightFindings()),
                ),
            ),
        ]
    )
    def test_a_broken_declaration_raises(self, _name: str, module: SimpleNamespace) -> None:
        with patch.object(highlight_registry, "load_product_modules", return_value=[module]):
            with self.assertRaises(highlight_registry.HighlightRegistryError):
                highlight_registry.load_sources.__wrapped__()
