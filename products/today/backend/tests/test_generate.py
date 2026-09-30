from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized

from products.today.backend.facade.enums import BriefingStatus, BriefingTrigger, BriefingWriter
from products.today.backend.logic.generate import write_and_check
from products.today.backend.models import DailyBriefing
from products.today.backend.tests.conftest import PRODUCT_DATABASES, TodayTeamScopedTestMixin
from products.today.backend.tests.test_checks import FACT_SHEET, VALID

INVENTED = {**VALID, "headline": "Orders fell 41% overnight."}


WRITE = "products.today.backend.logic.generate.write"


class TestWriteAndCheck(TodayTeamScopedTestMixin, BaseTest):
    databases = PRODUCT_DATABASES

    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()
        self.draft: dict[str, Any] = {"headline": "draft", "paragraphs": [], "labels": {}, "signals": {}}
        self.briefing = DailyBriefing.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            local_day=timezone.now().date(),
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
        with patch(WRITE, side_effect=[(answer, Decimal("0.03")) for answer in answers]) as write:
            write_and_check(team_id=self.team.id, briefing_id=str(self.briefing.id))

        self.briefing.refresh_from_db()
        assert self.briefing.status == BriefingStatus.READY
        assert self.briefing.writer == expected_writer
        assert self.briefing.content == (expected_content or self.draft)
        assert write.call_count == expected_calls
        assert self.briefing.llm_cost_usd == Decimal("0.03") * expected_calls
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
