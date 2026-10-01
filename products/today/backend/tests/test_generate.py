from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.sync import database_sync_to_async

from products.signals.backend.facade import api as signals
from products.today.backend.facade.enums import BriefingEdition, BriefingStatus, BriefingTrigger
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


class TestRunAgent(TodayTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.briefing = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
            edition=BriefingEdition.MORNING,
            timezone="UTC",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.COLLECTING,
        )
        self.reports = [
            _report("b", signals.BriefingReportRelation.SUGGESTED_REVIEWER, "P2"),
            _report("a", signals.BriefingReportRelation.WAITING_FOR_YOU, "P3"),
        ]

    def _run(self, *, on_start: Callable[[], None] | None = None) -> MagicMock:
        session = MagicMock()
        session.end = AsyncMock()

        async def start_raw(prompt: str, context: Any, **kwargs: Any) -> tuple[MagicMock, str]:
            if on_start:
                await database_sync_to_async(on_start, thread_sensitive=False)()
            return session, "Stored."

        with (
            patch(SANDBOX_ENV, return_value="env-1"),
            patch(REPORTS, return_value=self.reports),
            patch(f"{SESSION}.start_raw", side_effect=start_raw) as start,
            patch(FLAG, return_value=True),
        ):
            async_to_sync(run_agent)(team_id=self.team.id, briefing_id=str(self.briefing.id))
        return start

    def test_the_agent_runs_as_the_person_with_the_briefing_scopes(self) -> None:
        def store() -> None:
            DailyBriefing.objects.for_team(self.team.id).filter(id=self.briefing.id).update(status=BriefingStatus.READY)

        start = self._run(on_start=store)

        prompt, context = start.call_args.args
        assert str(self.briefing.id) in prompt
        # The pre-ranked reports go in best first: what waits for the person before what names them.
        assert prompt.index("report:a") < prompt.index("report:b")
        assert (context.user_id, context.posthog_mcp_scopes, context.model) == (self.user.id, "today_briefing", MODEL)
        assert context.initial_permission_mode == "full-access"
        # The run shows in the person's session list, under a name rather than the prompt.
        assert start.call_args.kwargs.get("internal", False) is False
        assert start.call_args.kwargs["on_task_run_created"] is not None

    def test_a_run_that_stores_nothing_fails_the_briefing(self) -> None:
        with self.assertRaises(RuntimeError):
            self._run()

        self.briefing.refresh_from_db()
        assert self.briefing.status == BriefingStatus.WRITING

    def test_no_sandbox_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        start = self._run()

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
