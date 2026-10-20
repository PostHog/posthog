import json
import datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import ActivityLog

from products.signals.backend.activity_summary.logic import ActivitySummaryUpdate, UpdateStatus, update_activity_summary
from products.signals.backend.models import UserActivitySummary
from products.signals.backend.test.test_activity_summary_render import FakeLLM

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
PATH_SECRET = "https://hooks.example.com/services/T000/B000/s3cr3tPathValue"
ANSWER = json.dumps(
    {
        "summary": "Builds the signup funnel.",
        "focus_areas": [{"topic": "signup funnel", "strength": "high", "last_seen": "2026-10-18"}],
        "products": ["product_analytics"],
        "recent_shift": None,
    }
)


@time_machine.travel(NOW, tick=False)
class TestUpdateActivitySummary(BaseTest):
    def _change(self, name: str, *, days_ago: float, intent: str | None = None, **overrides: Any) -> None:
        detail: dict[str, Any] = {"name": name}
        if intent:
            detail["trigger"] = {"job_type": "agent", "job_id": "", "payload": {"intent": intent}}
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope="Insight",
            activity="created",
            item_id=name,
            detail=detail,
            created_at=NOW - datetime.timedelta(days=days_ago),
            **overrides,
        )

    def _changes(self, count: int, *, days_ago: float = 1) -> None:
        for index in range(count):
            self._change(f"Funnel {index}", days_ago=days_ago + index / 100)

    def _update(self, llm: FakeLLM, **kwargs: Any) -> ActivitySummaryUpdate:
        with patch("products.signals.backend.activity_summary.logic.gateway_client", return_value=llm):
            return update_activity_summary(self.team.id, self.user.id, **kwargs)

    def _stored(self) -> UserActivitySummary | None:
        return UserActivitySummary.objects.for_team(self.team.id).filter(user_id=self.user.id).first()

    def test_a_successful_update_stores_the_summary_and_advances_the_watermark(self) -> None:
        self._changes(2, days_ago=2)
        self._change("Signup funnel", days_ago=1, intent=f"Post the funnel to {PATH_SECRET}")
        llm = FakeLLM([ANSWER])

        result = self._update(llm)

        assert result.status == UpdateStatus.OK
        sent = json.dumps(llm.requests[0]["messages"])
        assert "s3cr3tPathValue" not in sent and "[link hooks.example.com]" in sent
        stored = self._stored()
        assert stored is not None
        assert stored.status == UserActivitySummary.Status.OK
        assert stored.summary_text == "Builds the signup funnel.\nFocus areas: signup funnel"
        assert stored.input_watermark == NOW - datetime.timedelta(days=1)
        assert stored.next_eligible_at == NOW + datetime.timedelta(days=1)
        assert (stored.tokens_in, stored.tokens_out) == (100, 20)
        assert stored.cost_usd is not None
        assert stored.inputs_used["activity_lines"] == 3

        self._changes(3, days_ago=0.5)
        with time_machine.travel(NOW + datetime.timedelta(days=2), tick=False):
            next_llm = FakeLLM([ANSWER])
            assert self._update(next_llm).status == UpdateStatus.OK
        next_sent = json.dumps(next_llm.requests[0]["messages"])
        assert "Signup funnel" not in next_sent.split("Recent activity")[1]
        assert "Builds the signup funnel." in next_sent

    def test_a_failed_update_keeps_the_stored_summary_and_watermark(self) -> None:
        self._changes(3, days_ago=2)
        self._update(FakeLLM([ANSWER]))
        before = self._stored()
        assert before is not None
        self._changes(3, days_ago=0.5)

        result = self._update(FakeLLM([(ANSWER, "length")], usage=False), force=True)

        assert result.status == UpdateStatus.FAILED
        after = self._stored()
        assert after is not None
        assert after.status == UserActivitySummary.Status.FAILED
        assert after.error == "malformed_output: response was truncated"
        assert (after.summary, after.input_watermark) == (before.summary, before.input_watermark)
        assert (after.tokens_in, after.tokens_out, after.cost_usd) == (None, None, None)

    @parameterized.expand(
        [
            ("too few units", 2, {}, UpdateStatus.SKIPPED_TOO_FEW_UNITS),
            ("a dry run", 3, {"dry_run": True}, UpdateStatus.OK),
        ]
    )
    def test_writes_nothing(self, _name: str, changes: int, kwargs: dict[str, Any], status: UpdateStatus) -> None:
        self._changes(changes)
        self._change("Scout funnel", days_ago=1, client="scout:product-analytics")

        assert self._update(FakeLLM([ANSWER]), **kwargs).status == status
        assert self._stored() is None

    def test_skips_until_next_eligible_unless_forced(self) -> None:
        self._changes(3, days_ago=2)
        self._update(FakeLLM([ANSWER]))
        self._changes(3, days_ago=0.5)

        assert self._update(FakeLLM([ANSWER])).status == UpdateStatus.SKIPPED_NOT_ELIGIBLE_YET
        assert self._update(FakeLLM([ANSWER]), force=True).status == UpdateStatus.OK

    def test_skips_when_ai_data_processing_is_not_approved(self) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        self._changes(3)
        llm = FakeLLM([ANSWER])

        assert self._update(llm).status == UpdateStatus.SKIPPED_AI_NOT_APPROVED
        assert llm.requests == []
