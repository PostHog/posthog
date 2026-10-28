import json
import datetime
from typing import Any

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import ActivityLog, FileSystem, FileSystemViewLog, User

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.activity_summary.inputs import user_activity
from products.signals.backend.activity_summary.logic import ActivitySummaryUpdate, UpdateStatus, update_activity_summary
from products.signals.backend.activity_summary.prompt import PROMPT_VERSION
from products.signals.backend.activity_summary.render import RENDER_VERSION, RenderLimits
from products.signals.backend.models import UserActivitySummary, UserActivitySummaryVersion
from products.signals.backend.test.test_activity_summary_render import FakeLLM

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
PATH_SECRET = "https://hooks.example.com/services/T000/B000/s3cr3tPathValue"
ANSWER = json.dumps(
    {
        "profile": "## Funnels\n- Builds the signup funnel.",
        "headline": "Builds the signup funnel.",
        "themes": [{"label": "Signup funnel", "mode": "building", "strength": "high", "refs": ["o1"]}],
        "modes": ["building"],
        "recent_shift": None,
    }
)


@time_machine.travel(NOW, tick=False)
class TestUpdateActivitySummary(BaseTest):
    def _change(
        self, name: str, *, days_ago: float, intent: str | None = None, scope: str = "Insight", **overrides: Any
    ) -> None:
        detail: dict[str, Any] = {"name": name}
        if intent:
            detail["trigger"] = {"job_type": "agent", "job_id": "", "payload": {"intent": intent}}
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope=scope,
            detail=detail,
            created_at=NOW - datetime.timedelta(days=days_ago),
            **{"activity": "created", "item_id": name, **overrides},
        )

    def _changes(self, count: int, *, days_ago: float = 1) -> None:
        for index in range(count):
            self._change(f"Funnel {index}", days_ago=days_ago + index / 100)

    def _update(self, llm: FakeLLM, **kwargs: Any) -> ActivitySummaryUpdate:
        with patch("products.signals.backend.activity_summary.logic.gateway_client", return_value=llm):
            return update_activity_summary(self.team.id, self.user.id, **kwargs)

    def _stored(self) -> UserActivitySummary | None:
        return UserActivitySummary.objects.for_team(self.team.id).filter(user_id=self.user.id).first()

    def _versions(self) -> list[int]:
        return list(
            UserActivitySummaryVersion.objects.for_team(self.team.id)
            .filter(summary_row__user_id=self.user.id)
            .order_by("version")
            .values_list("version", flat=True)
        )

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
        assert stored.summary_text == "Builds the signup funnel.\nThemes: Signup funnel"
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
        latest = self._stored()
        assert latest is not None and latest.version == 2
        assert self._versions() == [1, 2]
        first = UserActivitySummaryVersion.objects.for_team(self.team.id).get(summary_row=latest, version=1)
        assert (first.summary_text, first.input_watermark) == (stored.summary_text, stored.input_watermark)
        # The second update read only the rows after the watermark, but its computed fields cover the full window.
        assert latest.computed is not None
        assert {entry["id"] for entry in latest.computed["owned"]} == {
            "Funnel 0",
            "Funnel 1",
            "Funnel 2",
            "Signup funnel",
        }
        second = UserActivitySummaryVersion.objects.for_team(self.team.id).get(summary_row=latest, version=2)
        assert second.computed == latest.computed

    def test_a_person_who_only_reads_gets_a_summary_from_what_they_opened(self) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", None)
        for ref, name, creator in [("abc", "Weekly signups", other), ("def", "Churn by plan", self.user)]:
            FileSystem.objects.create(
                team=self.team, type="insight", ref=ref, path=f"Unfiled/{name}", created_by=creator
            )
        views = [
            ("insight", "abc", 2),
            ("insight", "def", 1.5),
            ("scene", "Experiments", 1),
            ("scene", "Settings", 0.5),
        ]
        for view_type, ref, days_ago in views:
            viewed_at = NOW - datetime.timedelta(days=days_ago)
            FileSystemViewLog.objects.create(
                team=self.team,
                user=self.user,
                type=view_type,
                ref=ref,
                viewed_at=viewed_at,
                view_days=[viewed_at.date()],
            )
        llm = FakeLLM([ANSWER])

        result = self._update(llm)

        assert result.status == UpdateStatus.OK
        assert result.rendered_input is not None
        assert '- Insight "Weekly signups": opened 1 day, last 2026-10-17, not theirs' in result.rendered_input
        assert '- Insight "Churn by plan": opened 1 day, last 2026-10-18\n' in result.rendered_input
        assert "- Experiments pages: opened 1 day, last 2026-10-18" in result.rendered_input
        stored = self._stored()
        assert stored is not None
        assert stored.inputs_used["view_lines"] == 3
        assert stored.inputs_used["drops"] == {"generic_scene": 1}
        assert stored.input_watermark == NOW - datetime.timedelta(days=0.5)

    def test_limits_reach_the_model_call_and_the_stored_inputs(self) -> None:
        self._changes(3, days_ago=2)
        self._change("Old funnel", days_ago=10)
        llm = FakeLLM([ANSWER])

        self._update(llm, limits=RenderLimits(window_days=7, profile_max_chars=12, max_completion_tokens=1234))

        stored = self._stored()
        assert stored is not None and stored.summary is not None
        assert llm.requests[0]["max_completion_tokens"] == 1234
        assert "at most 12 characters" in llm.requests[0]["messages"][0]["content"]
        assert stored.summary["profile"] == "## Funnels…"
        assert stored.inputs_used["activity_lines"] == 3
        assert stored.inputs_used["limits"]["max_completion_tokens"] == 1234

    def test_insights_on_a_dashboard_render_as_one_line_for_the_dashboard(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="Quality review")
        self._change("Quality review", days_ago=1.2, scope="Dashboard", item_id=str(dashboard.id))
        for index, name in enumerate(["Records judged per day", "Suggestion defect rates"]):
            insight = Insight.objects.create(team=self.team, name=name)
            DashboardTile.objects.create(dashboard=dashboard, insight=insight)
            self._change(name, days_ago=1.1 - index / 100, item_id=str(insight.id))

        result = self._update(FakeLLM([ANSWER]), dry_run=True, min_units=1)

        assert result.rendered_input is not None and result.inputs_used is not None
        assert result.rendered_input.splitlines()[1:] == [
            '- 2026-10-18 created Dashboard "Quality review" with 2 Insights: '
            '"Suggestion defect rates", "Records judged per day"'
        ]
        assert result.inputs_used["drops"] == {"grouped_into_parent": 2}

    @parameterized.expand(
        [
            ("an older prompt version", {"prompt_version": PROMPT_VERSION - 1}, {}, True),
            ("an older render version", {"render_version": RENDER_VERSION - 1}, {}, True),
            ("a rebuild_before after generated_at", {}, {"rebuild_before": NOW - datetime.timedelta(hours=1)}, True),
            ("a rebuild_before before generated_at", {}, {"rebuild_before": NOW - datetime.timedelta(days=3)}, False),
        ]
    )
    def test_a_stale_summary_rebuilds_from_the_full_window(
        self, _name: str, stored_fields: dict[str, Any], kwargs: dict[str, Any], rebuilt: bool
    ) -> None:
        for index in range(3):
            self._change(f"Old dashboard {index}", days_ago=5 + index / 100)
        UserActivitySummary.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            user_id=self.user.id,
            status=UserActivitySummary.Status.OK,
            summary=json.loads(ANSWER) | {"headline": "Old stored summary."},
            generated_at=NOW - datetime.timedelta(days=2),
            input_watermark=NOW - datetime.timedelta(days=2),
            **({"prompt_version": PROMPT_VERSION, "render_version": RENDER_VERSION} | stored_fields),
        )
        self._changes(3, days_ago=1)
        llm = FakeLLM([ANSWER])

        result = self._update(llm, **kwargs)

        assert (result.status, result.rebuilt) == (UpdateStatus.OK, rebuilt)
        sent = json.dumps(llm.requests[0]["messages"])
        assert ("Old stored summary." not in sent) == rebuilt
        assert ("Old dashboard" in sent.split("Recent activity")[1]) == rebuilt
        stored = self._stored()
        assert stored is not None
        assert (stored.prompt_version, stored.render_version) == (PROMPT_VERSION, RENDER_VERSION)

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
        assert after.next_eligible_at == NOW + datetime.timedelta(hours=6)
        assert after.version == before.version == 1
        assert self._versions() == [1]

    def test_keeps_the_latest_max_versions_and_deletes_them_with_the_summary(self) -> None:
        for update in range(3):
            self._changes(3, days_ago=2 - update / 2)
            assert self._update(FakeLLM([ANSWER]), force=True, max_versions=2).status == UpdateStatus.OK

        assert self._versions() == [2, 3]
        stored = self._stored()
        assert stored is not None and stored.version == 3
        stored.delete()
        assert self._versions() == []

    @parameterized.expand(
        [
            ("too few units in a dry run", 2, {"dry_run": True}, UpdateStatus.SKIPPED_TOO_FEW_UNITS),
            ("a dry run", 3, {"dry_run": True}, UpdateStatus.OK),
        ]
    )
    def test_writes_nothing(self, _name: str, changes: int, kwargs: dict[str, Any], status: UpdateStatus) -> None:
        self._changes(changes)
        self._change("Scout funnel", days_ago=1, client="scout:product-analytics")

        assert self._update(FakeLLM([ANSWER]), **kwargs).status == status
        assert self._stored() is None

    @patch("products.signals.backend.activity_summary.inputs.MAX_ACTIVITY_ROWS_PER_PERSON", 1)
    def test_noisy_rows_do_not_use_the_read_limit(self) -> None:
        self._change("Signup funnel", days_ago=2)
        self._change("Tagged report", days_ago=1, scope="TaggedItem")
        self._change("Scout funnel", days_ago=1, client="scout:product-analytics")

        rows = user_activity(self.team.id, self.user.id, NOW - datetime.timedelta(days=28), NOW)

        assert [row.name for row in rows] == ["Signup funnel"]

    def test_too_few_units_backs_off_without_touching_the_stored_summary(self) -> None:
        self._changes(2)
        llm = FakeLLM([ANSWER])

        assert self._update(llm).status == UpdateStatus.SKIPPED_TOO_FEW_UNITS
        assert llm.requests == []
        skipped = self._stored()
        assert skipped is not None
        assert (skipped.status, skipped.summary) == (UserActivitySummary.Status.SKIPPED, None)
        assert skipped.next_eligible_at == NOW + datetime.timedelta(hours=6)
        with time_machine.travel(NOW + datetime.timedelta(hours=7), tick=False):
            assert self._update(llm).status == UpdateStatus.SKIPPED_TOO_FEW_UNITS
        skipped_again = self._stored()
        assert skipped_again is not None
        assert skipped_again.next_eligible_at == NOW + datetime.timedelta(hours=7 + 12)

        with time_machine.travel(NOW + datetime.timedelta(hours=20), tick=False):
            assert self._update(FakeLLM([ANSWER]), min_units=2).status == UpdateStatus.OK
        before = self._stored()
        assert before is not None
        with time_machine.travel(NOW + datetime.timedelta(days=2), tick=False):
            assert self._update(FakeLLM([ANSWER])).status == UpdateStatus.SKIPPED_TOO_FEW_UNITS
        after = self._stored()
        assert after is not None
        assert (after.status, after.summary, after.updated_at) == (before.status, before.summary, before.updated_at)
        assert after.next_eligible_at == NOW + datetime.timedelta(days=2, hours=6)

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
