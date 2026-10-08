import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from pydantic import ValidationError

from posthog.sync import database_sync_to_async

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import BriefingStatus, BriefingTrigger, BriefingWriter
from products.today.backend.logic.fact_sheet import fact_sheet_for_reports
from products.today.backend.logic.generate import write_briefing
from products.today.backend.models import DailyBriefing
from products.today.backend.temporal.activities import _due_briefings
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin

FLAG = "products.today.backend.feature_flags.feature_enabled_or_false"
LIMITED = "products.today.backend.feature_flags.is_team_limited"
# The activity hops to a worker thread for the ORM; under the test transaction that thread would not
# see the rows, so the hop runs on the test thread instead.
ON_TEST_THREAD = "products.today.backend.logic.generate.database_sync_to_async"


def _on_test_thread(fn: Callable[..., Any], **_: Any) -> Callable[..., Any]:
    return database_sync_to_async(fn, thread_sensitive=True)


CLIENT = "products.today.backend.logic.generate.build_async_openai_client"
REPORTS = "products.today.backend.logic.generate.signals.reports_for_briefing"


def _report(report_id: str, relation: signals.BriefingReportRelation, priority: str) -> signals.BriefingReport:
    return signals.BriefingReport(
        report_id=report_id,
        relation=relation,
        title=f"Report {report_id}",
        summary="",
        status="ready",
        priority=priority,
        has_implementation_pr=False,
        source_products=["error_tracking"],
        updated_at=datetime(2026, 9, 30, tzinfo=UTC),
        pr_merged_probability=None,
    )


def _reply(content: str) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    return response


def _answer() -> str:
    return json.dumps(
        {
            "headline": "Two reports need your input",
            "paragraphs": [
                [
                    {"text": "The ", "item_key": None},
                    {"text": "report b", "item_key": "report:b"},
                    {"text": " waits for a review. ", "item_key": None},
                    {"text": "Report a", "item_key": "report:a"},
                    {"text": " waits for you, like ", "item_key": None},
                    {"text": "an invented report", "item_key": "report:invented"},
                    {"text": ".", "item_key": None},
                ]
            ],
            "items": [
                {"key": "report:b", "label": "Report b", "signal": "P2, review asked"},
                {"key": "report:a", "label": "Report a", "signal": "Waits for you"},
                {"key": "report:invented", "label": "Invented", "signal": "Made up"},
            ],
        }
    )


class TestWriteBriefing(TodayTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.previous = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date() - timedelta(days=1),
            timezone="UTC",
            trigger=BriefingTrigger.SCHEDULED,
            status=BriefingStatus.READY,
            content={"headline": "Yesterday's headline", "paragraphs": [], "labels": {}, "signals": {}},
            facts=fact_sheet_for_reports(
                [_report("a", signals.BriefingReportRelation.WAITING_FOR_YOU, "P3")], self.team.id
            ).model_dump(mode="json"),
        )
        self.briefing = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
            timezone="UTC",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.COLLECTING,
        )
        self.reports = [
            _report("b", signals.BriefingReportRelation.SUGGESTED_REVIEWER, "P2"),
            _report("a", signals.BriefingReportRelation.WAITING_FOR_YOU, "P3"),
        ]

    def _run(self, reply: str = "") -> AsyncMock:
        create = AsyncMock(return_value=_reply(reply))
        opened = MagicMock()
        opened.chat.completions.create = create
        client = MagicMock()
        client.with_options.return_value.__aenter__.return_value = opened
        with (
            patch(ON_TEST_THREAD, _on_test_thread),
            patch(REPORTS, return_value=self.reports) as reports,
            patch(CLIENT, return_value=client),
            patch(FLAG, return_value=True),
        ):
            async_to_sync(write_briefing)(team_id=self.team.id, briefing_id=str(self.briefing.id))
        self.reports_asked_for = reports.call_args.kwargs if reports.call_args else {}
        return create

    def test_the_items_are_the_ranked_reports_and_the_llm_writes_only_the_text(self) -> None:
        create = self._run(_answer())

        self.briefing.refresh_from_db()
        assert (self.briefing.status, self.briefing.writer) == (BriefingStatus.READY, BriefingWriter.AGENT)
        assert [(item["key"], item["reason"], item["url"]) for item in self.briefing.facts["items"]] == [
            ("report:b", "suggested_reviewer", f"/project/{self.team.id}/inbox/b"),
            ("report:a", "waiting_for_you", f"/project/{self.team.id}/inbox/a"),
        ]
        content = self.briefing.content
        assert content["headline"] == "Two reports need your input"
        linked = [segment["item_key"] for segment in content["paragraphs"][0] if segment["item_key"]]
        assert linked == ["report:b", "report:a"]
        highlighted = [segment["item_key"] for segment in content["paragraphs"][0] if segment["highlight"]]
        assert highlighted == ["report:b"]
        assert "an invented report" in "".join(segment["text"] for segment in content["paragraphs"][0])
        assert set(content["labels"]) == set(content["signals"]) == {"report:b", "report:a"}
        create.assert_awaited_once()
        prompt = create.call_args.kwargs["messages"][0]["content"]
        assert prompt.index("report:b") < prompt.index("report:a")
        assert "Yesterday's headline" in prompt

    def test_the_briefing_asks_for_the_persons_own_reports_only(self) -> None:
        self._run(_answer())

        # A P0 nobody owns sorts above every item that is the person's, so the briefing leaves it to
        # the Inbox and to the open-in-project count.
        assert self.reports_asked_for["include_unowned"] is False

    def test_no_reports_means_no_llm_call(self) -> None:
        self.reports = []

        create = self._run()

        self.briefing.refresh_from_db()
        create.assert_not_called()
        assert self.briefing.status == BriefingStatus.READY
        assert (self.briefing.content["headline"], self.briefing.facts["items"]) == ("", [])

    def test_a_reply_that_is_not_a_briefing_fails_the_attempt_and_stores_nothing(self) -> None:
        with self.assertRaises(ValidationError):
            self._run("I could not write the briefing.")

        self.briefing.refresh_from_db()
        assert (self.briefing.status, self.briefing.content) == (BriefingStatus.WRITING, {})

    def test_no_llm_call_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        create = self._run(_answer())

        create.assert_not_called()
        assert not DailyBriefing.objects.for_team(self.team.id).filter(id=self.briefing.id).exists()


class TestWhoGetsABriefing(TodayTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    def _viewer_row(self) -> DailyBriefing:
        return DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=date(2026, 9, 29),
            timezone="Europe/Prague",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.READY,
            last_viewed_at=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        )

    @parameterized.expand(
        [
            # Prague is UTC+2, so 05:50 UTC is 07:50 local time: the day starts within the window.
            ("before eight", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), {}, True),
            ("later in the day", datetime(2026, 9, 30, 9, 50, tzinfo=UTC), {}, False),
            ("flag off", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), {"flag": False}, False),
            ("left the organization", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), {"member": False}, False),
            ("ai data processing not approved", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), {"approved": False}, False),
            ("out of ai credits", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), {"limited": True}, False),
            ("last opened Today over a week ago", datetime(2026, 10, 7, 5, 50, tzinfo=UTC), {}, False),
        ]
    )
    def test_scheduler_writes_the_day_ahead_only_for_recent_viewers_who_may_get_one(
        self, _name: str, now: datetime, case: dict[str, bool], expected: bool
    ) -> None:
        self._viewer_row()
        if not case.get("member", True):
            self.organization_membership.delete()
        self.organization.is_ai_data_processing_approved = case.get("approved", True)
        self.organization.save()

        with (
            time_machine.travel(now, tick=False),
            patch(FLAG, return_value=case.get("flag", True)),
            patch(LIMITED, return_value=case.get("limited", False)),
        ):
            created = _due_briefings()
            again = _due_briefings()

        assert [row.local_day for row in created] == ([now.date()] if expected else [])
        # The next tick returns the same pending row for dispatch, and never a second one.
        assert [row.id for row in again] == [row.id for row in created]

    def test_the_run_deletes_the_row_when_the_flag_turned_off(self) -> None:
        briefing = self._viewer_row()

        with (
            patch(ON_TEST_THREAD, _on_test_thread),
            patch(FLAG, return_value=False),
            patch(CLIENT) as client,
        ):
            async_to_sync(write_briefing)(team_id=self.team.id, briefing_id=str(briefing.id))

        client.assert_not_called()
        assert not DailyBriefing.objects.for_team(self.team.id).filter(id=briefing.id).exists()
