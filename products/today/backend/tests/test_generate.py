from datetime import UTC, date, datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.today.backend.facade.enums import BriefingEdition, BriefingStatus, BriefingTrigger, BriefingWriter
from products.today.backend.logic.generate import draft_briefing, write_and_check
from products.today.backend.models import DailyBriefing
from products.today.backend.temporal.activities import _due_briefings
from products.today.backend.tests.conftest import TodayTeamScopedTestMixin
from products.today.backend.tests.test_checks import FACT_SHEET, VALID

INVENTED = {**VALID, "headline": "Orders fell 41% overnight."}


WRITE = "products.today.backend.logic.generate.write"


class TestWriteAndCheck(TodayTeamScopedTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.draft: dict[str, Any] = {"headline": "draft", "paragraphs": [], "labels": {}, "signals": {}}
        self.briefing = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
            edition=BriefingEdition.MORNING,
            timezone="UTC",
            trigger=BriefingTrigger.FIRST_OPEN,
            status=BriefingStatus.WRITING,
            writer=BriefingWriter.TEMPLATE,
            facts=FACT_SHEET,
            draft=self.draft,
            content=self.draft,
        )

    @parameterized.expand(
        [
            ("first answer passes", [VALID], BriefingWriter.LLM, VALID, 1),
            ("retry with the problems passes", [INVENTED, VALID], BriefingWriter.LLM, VALID, 2),
            ("both answers fail the checks", [INVENTED, INVENTED], BriefingWriter.TEMPLATE, None, 2),
        ]
    )
    def test_only_checked_text_replaces_the_draft(
        self,
        _name: str,
        answers: list[dict[str, Any]],
        expected_writer: BriefingWriter,
        expected_content: dict[str, Any] | None,
        expected_calls: int,
    ) -> None:
        with patch(WRITE, side_effect=list(answers)) as write:
            write_and_check(team_id=self.team.id, briefing_id=str(self.briefing.id))

        self.briefing.refresh_from_db()
        assert self.briefing.status == BriefingStatus.READY
        assert self.briefing.writer == expected_writer
        assert self.briefing.content == (expected_content or self.draft)
        assert write.call_count == expected_calls
        if expected_calls == 2:
            assert write.call_args.kwargs["problems"]

    def test_no_llm_call_without_ai_data_processing_approval(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        with patch(WRITE) as write:
            write_and_check(team_id=self.team.id, briefing_id=str(self.briefing.id))

        self.briefing.refresh_from_db()
        write.assert_not_called()
        assert (self.briefing.status, self.briefing.content) == (BriefingStatus.READY, self.draft)


FLAG = "products.today.backend.feature_flags.feature_enabled_or_false"


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

    def test_draft_deletes_the_row_when_the_flag_turned_off(self) -> None:
        briefing = self._viewer_row()

        with patch(FLAG, return_value=False):
            eligible = draft_briefing(
                team_id=self.team.id, briefing_id=str(briefing.id), candidates=[], failed_sources=[]
            )

        assert eligible is False
        assert not DailyBriefing.objects.for_team(self.team.id).filter(id=briefing.id).exists()
