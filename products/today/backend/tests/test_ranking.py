from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Team, User

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import ItemGroup, ItemReason, ItemSource
from products.today.backend.logic.candidates import Candidate, SourceContext
from products.today.backend.logic.eligibility import is_due, local_day
from products.today.backend.logic.ranking import rank_candidates, select
from products.today.backend.logic.sources import reports as report_source


def _candidate(key: str, group: ItemGroup, order: float = 0) -> Candidate:
    return Candidate(
        key=key,
        group=group,
        source=ItemSource.SELF_DRIVING,
        reason=ItemReason.WAITING_FOR_YOU,
        title=key,
        url="",
        sort_key=(order,),
        facts={},
    )


class TestRanking(SimpleTestCase):
    def test_many_reports_do_not_push_other_text_items_out_of_the_left_bar(self) -> None:
        reports = [_candidate(f"report:{i}", ItemGroup.REPORT, i) for i in range(14)]
        others = [_candidate("dashboard:1", ItemGroup.DASHBOARD), _candidate("ticket:1", ItemGroup.OTHER)]

        items = select(rank_candidates(reports + others))

        in_text = [item.candidate.key for item in items if item.in_text]
        assert in_text == ["report:0", "report:1", "report:2", "dashboard:1", "ticket:1"]
        assert len(items) == 10
        assert {"dashboard:1", "ticket:1"} <= {item.candidate.key for item in items}
        assert [item.rank for item in items] == sorted(item.rank for item in items)

    @parameterized.expand(
        [
            ("first report", ["dashboard:1", "report:2", "report:1"], "report:1"),
            ("no reports", ["ticket:1", "dashboard:2", "dashboard:1"], "dashboard:1"),
            ("only other", ["ticket:1"], "ticket:1"),
        ]
    )
    def test_top_item(self, _name: str, keys: list[str], expected_top: str) -> None:
        groups = {"report": ItemGroup.REPORT, "dashboard": ItemGroup.DASHBOARD, "ticket": ItemGroup.OTHER}
        candidates = [_candidate(key, groups[key.split(":")[0]], int(key.split(":")[1])) for key in keys]

        items = select(rank_candidates(candidates))

        assert [item.candidate.key for item in items if item.top] == [expected_top]

    def test_the_same_item_from_two_sources_appears_once(self) -> None:
        items = select(
            rank_candidates([_candidate("report:1", ItemGroup.REPORT), _candidate("report:1", ItemGroup.REPORT)])
        )

        assert [item.candidate.key for item in items] == ["report:1"]


def _report(
    report_id: str,
    priority: str,
    merge_chance: float | None,
    relation: signals.BriefingReportRelation = signals.BriefingReportRelation.WAITING_FOR_YOU,
) -> signals.BriefingReport:
    return signals.BriefingReport(
        report_id=report_id,
        relation=relation,
        title=report_id,
        summary="",
        status="pending_input",
        priority=priority,
        has_implementation_pr=False,
        updated_at=datetime(2026, 9, 29, tzinfo=UTC),
        pr_merged_probability=merge_chance,
    )


class TestReportOrder(SimpleTestCase):
    @parameterized.expand(
        [
            ("merge chance beats priority", [_report("a", "P2", 0.8), _report("b", "P1", 0.2)], ["a", "b"]),
            ("P0 stays first", [_report("b", "P1", 0.9), _report("a", "P0", 0.05)], ["a", "b"]),
            ("unscored reports follow scored ones", [_report("a", "P1", None), _report("b", "P3", 0.1)], ["b", "a"]),
            ("no scores falls back to priority", [_report("a", "P3", None), _report("b", "P1", None)], ["b", "a"]),
            (
                "relation beats merge chance",
                [
                    _report("b", "P1", 0.9),
                    _report("a", "P3", 0.01, relation=signals.BriefingReportRelation.CLAIMED),
                ],
                ["a", "b"],
            ),
        ]
    )
    def test_report_order(self, _name: str, reports: list[signals.BriefingReport], expected: list[str]) -> None:
        ctx = SourceContext(
            team=cast(Team, SimpleNamespace(id=1)),
            user=cast(User, SimpleNamespace(id=1)),
            now=datetime(2026, 9, 30, tzinfo=UTC),
        )
        with patch.object(report_source.signals, "reports_for_briefing", return_value=reports):
            ranked = rank_candidates(report_source.collect(ctx))

        assert [item.key for item in ranked] == [f"report:{report_id}" for report_id in expected]


class TestBriefingDay(SimpleTestCase):
    @parameterized.expand(
        [
            ("before 8:00 is still yesterday", datetime(2026, 9, 30, 5, 30, tzinfo=UTC), "Europe/Prague", "2026-09-29"),
            ("after 8:00 is today", datetime(2026, 9, 30, 6, 30, tzinfo=UTC), "Europe/Prague", "2026-09-30"),
            ("the zone decides", datetime(2026, 9, 30, 13, 0, tzinfo=UTC), "America/Los_Angeles", "2026-09-29"),
        ]
    )
    def test_local_day(self, _name: str, now: datetime, zone: str, expected: str) -> None:
        assert local_day(now, zone).isoformat() == expected

    @parameterized.expand(
        [
            ("in the window", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), True),
            ("at 8:00 the window has closed", datetime(2026, 9, 30, 6, 0, tzinfo=UTC), False),
            ("too early", datetime(2026, 9, 30, 5, 40, tzinfo=UTC), False),
        ]
    )
    def test_is_due_15_minutes_before_8_in_prague(self, _name: str, now: datetime, expected: bool) -> None:
        assert is_due(now, "Europe/Prague", 15) is expected
