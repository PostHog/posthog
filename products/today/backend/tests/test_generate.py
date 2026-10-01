from datetime import UTC, date, datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import BriefingEdition, BriefingStatus, BriefingTrigger, BriefingWriter
from products.today.backend.logic.agent_output import BriefingOutput, to_fact_sheet
from products.today.backend.logic.generate import MODEL, run_agent
from products.today.backend.models import DailyBriefing
from products.today.backend.temporal.activities import _due_briefings
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin

FLAG = "products.today.backend.feature_flags.feature_enabled_or_false"
SESSION = "products.today.backend.logic.generate.MultiTurnSession"
SANDBOX_ENV = "products.today.backend.logic.generate.tasks_facade.upsert_internal_sandbox_env"
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


def _output(headline: str = "One report needs your input", **item_overrides: Any) -> BriefingOutput:
    item = {
        "key": "report:a",
        "group": "report",
        "source": "self_driving",
        "reason": "waiting_for_you",
        "title": "Report a",
        "label": "Report a",
        "signal": "P3, waits for you",
        "url": "/project/1/inbox/a",
        "urgency": 0,
        "source_product": "error_tracking",
        "facts": [{"name": "priority", "value": "P3"}],
        **item_overrides,
    }
    return BriefingOutput.model_validate(
        {
            "headline": headline,
            "paragraphs": [
                [
                    {"text": "The ", "item_key": None, "highlight": False},
                    {"text": "report a", "item_key": "report:a", "highlight": True},
                    {"text": " waits for your call.", "item_key": None, "highlight": False},
                ]
            ],
            "items": [item],
        }
    )


class TestRunAgent(TodayTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.previous = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
            edition=BriefingEdition.MORNING,
            timezone="UTC",
            trigger=BriefingTrigger.SCHEDULED,
            status=BriefingStatus.READY,
            content={"headline": "Yesterday's headline", "paragraphs": [], "labels": {}, "signals": {}},
        )
        self.previous.facts = to_fact_sheet(_output(), self.previous, self.user).model_dump(mode="json")
        self.previous.save(update_fields=["facts"])
        self.briefing = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
            edition=BriefingEdition.MIDDAY,
            timezone="UTC",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.COLLECTING,
        )
        self.reports = [
            _report("b", signals.BriefingReportRelation.SUGGESTED_REVIEWER, "P2"),
            _report("a", signals.BriefingReportRelation.WAITING_FOR_YOU, "P3"),
        ]

    def _run(self, first: BriefingOutput, *followups: BriefingOutput) -> tuple[MagicMock, MagicMock]:
        session = MagicMock()
        session.end = AsyncMock()
        session.send_followup = AsyncMock(side_effect=list(followups))
        start = AsyncMock(return_value=(session, first))
        with (
            patch(SANDBOX_ENV, return_value="env-1"),
            patch(REPORTS, return_value=self.reports),
            patch(f"{SESSION}.start", start),
            patch(FLAG, return_value=True),
        ):
            async_to_sync(run_agent)(team_id=self.team.id, briefing_id=str(self.briefing.id))
        return start, session

    def test_a_good_answer_is_stored_and_the_run_was_read_only(self) -> None:
        start, session = self._run(_output())

        self.briefing.refresh_from_db()
        assert (self.briefing.status, self.briefing.writer) == (BriefingStatus.READY, BriefingWriter.AGENT)
        assert self.briefing.content["headline"] == "One report needs your input"
        assert self.briefing.facts["items"][0]["source_product"] == "error_tracking"
        prompt, context = start.call_args.args
        assert (context.user_id, context.posthog_mcp_scopes, context.model) == (self.user.id, "read_only", MODEL)
        assert start.call_args.kwargs["model"] is BriefingOutput
        # The pre-ranked reports go in best first, and the previous briefing is there to avoid repeats.
        assert prompt.index("report:a") < prompt.index("report:b")
        assert "Yesterday's headline" in prompt
        assert start.call_args.kwargs.get("internal", False) is False
        session.end.assert_awaited_once_with()

    def test_an_answer_that_breaks_a_rule_comes_back_fixed_in_a_follow_up(self) -> None:
        start, session = self._run(_output(headline="One report needs you — now"), _output())

        self.briefing.refresh_from_db()
        assert self.briefing.status == BriefingStatus.READY
        [(message, model), _] = [(call.args, call.kwargs) for call in session.send_followup.call_args_list]
        assert "em or en dash" in message and model is BriefingOutput

    def test_an_answer_that_keeps_breaking_rules_fails_the_run(self) -> None:
        broken = _output(headline="One report needs you — now")
        with self.assertRaises(RuntimeError):
            self._run(broken, broken, broken)

        self.briefing.refresh_from_db()
        assert self.briefing.status == BriefingStatus.WRITING

    def test_no_sandbox_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        start, _ = self._run(_output())

        start.assert_not_called()
        assert not DailyBriefing.objects.for_team(self.team.id).filter(id=self.briefing.id).exists()


class TestNoBriefingWithoutTheFlag(TodayTeamScopedTestMixin, BaseTest):
    def _viewer_row(self) -> DailyBriefing:
        return DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=date(2026, 9, 29),
            edition=BriefingEdition.MIDDAY,
            timezone="Europe/Prague",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.READY,
            last_viewed_at=datetime(2026, 9, 29, 9, 0, tzinfo=UTC),
        )

    @parameterized.expand(
        [
            # Prague is UTC+2, so 05:50 UTC is 07:50 and 09:50 UTC is 11:50 local time.
            ("morning edition", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), True, [BriefingEdition.MORNING]),
            ("midday edition", datetime(2026, 9, 30, 9, 50, tzinfo=UTC), True, [BriefingEdition.MIDDAY]),
            ("between editions", datetime(2026, 9, 30, 7, 0, tzinfo=UTC), True, []),
            ("flag off", datetime(2026, 9, 30, 5, 50, tzinfo=UTC), False, []),
        ]
    )
    def test_scheduler_writes_each_edition_ahead_only_with_the_flag(
        self, _name: str, now: datetime, enabled: bool, expected: list[BriefingEdition]
    ) -> None:
        self._viewer_row()

        with time_machine.travel(now, tick=False), patch(FLAG, return_value=enabled):
            created = _due_briefings()
            again = _due_briefings()

        assert [(row.local_day, row.edition) for row in created] == [
            (date(2026, 9, 30), edition) for edition in expected
        ]
        assert again == []

    def test_the_run_deletes_the_row_when_the_flag_turned_off(self) -> None:
        briefing = self._viewer_row()

        with patch(FLAG, return_value=False), patch(SANDBOX_ENV) as sandbox_env:
            async_to_sync(run_agent)(team_id=self.team.id, briefing_id=str(briefing.id))

        sandbox_env.assert_not_called()
        assert not DailyBriefing.objects.for_team(self.team.id).filter(id=briefing.id).exists()
