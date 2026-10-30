import datetime

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from posthog.models import ActivityLog, Organization, Team, User

from products.signals.backend.activity_summary import tick
from products.signals.backend.activity_summary.backfill import (
    BACKFILL_DOCUMENT_TYPE,
    BackfillJob,
    BackfillOptions,
    backfill_jobs,
    plan_backfill,
    run_backfill,
)
from products.signals.backend.activity_summary.queue import max_update_cost_usd
from products.signals.backend.models import (
    SignalReport,
    SignalReportAction,
    UserActivitySummary,
    UserActivitySummaryVersion,
)
from products.signals.backend.test.test_activity_summary_render import FakeLLM
from products.signals.backend.test.test_activity_summary_update import ANSWER

NOW = datetime.datetime(2026, 10, 19, 12, tzinfo=datetime.UTC)
AS_OF = datetime.datetime(2026, 10, 10, tzinfo=datetime.UTC)
GATEWAY = "products.signals.backend.activity_summary.logic.gateway_client"


@time_machine.travel(NOW, tick=False)
class TestActivitySummaryBackfill(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.is_ai_training_opted_in = True
        self.organization.save()

    def _changes(self, team: Team, user: User, count: int) -> None:
        for index in range(count):
            ActivityLog.objects.create(
                team_id=team.id,
                organization_id=team.organization_id,
                user=user,
                scope="Insight",
                activity="created",
                item_id=f"funnel-{index}",
                detail={"name": f"Funnel {index}"},
                created_at=AS_OF - datetime.timedelta(days=1, hours=index),
            )

    def _inbox_action(self, team: Team, user: User) -> None:
        report = SignalReport.objects.create(team=team, status="ready", title="Report", summary="Summary")
        with time_machine.travel(AS_OF - datetime.timedelta(days=2), tick=False):
            SignalReportAction.record(
                team_id=team.id,
                report_id=str(report.id),
                user_id=user.id,
                action_type=SignalReportAction.ActionType.VIEW,
            )

    def _jobs(self, count: int) -> list[BackfillJob]:
        return [
            BackfillJob(team_id=self.team.id, user_id=self.user.id, as_of=AS_OF - datetime.timedelta(days=n))
            for n in range(count)
        ]

    def test_inbox_users_on_teams_without_training_consent_get_no_job(self) -> None:
        other_org = Organization.objects.create(
            name="Other", is_ai_data_processing_approved=True, is_ai_training_opted_in=False
        )
        other_team = Team.objects.create(organization=other_org)
        other_user = User.objects.create_and_join(other_org, "other@example.com", None)
        self._inbox_action(self.team, self.user)
        self._inbox_action(other_team, other_user)

        jobs = backfill_jobs([AS_OF, AS_OF - datetime.timedelta(days=3)])

        assert jobs == [BackfillJob(team_id=self.team.id, user_id=self.user.id, as_of=AS_OF)]

    def test_a_run_emits_backfill_vectors_and_events_and_writes_no_live_state(self) -> None:
        self._changes(self.team, self.user, 3)
        capture = MagicMock()
        with (
            patch(GATEWAY, return_value=FakeLLM([ANSWER])),
            patch("posthog.api.embedding_worker.emit_embedding_request") as emit,
            patch.object(tick, "ph_background_capture", return_value=capture),
        ):
            result = run_backfill(self._jobs(1), BackfillOptions(exclude_inbox=True), max_cost_usd=10.0)

        assert result.statuses == {"ok": 1}
        embedding = emit.call_args.kwargs
        assert embedding["document_type"] == BACKFILL_DOCUMENT_TYPE
        assert embedding["document_id"] == f"{self.user.id}:2026-10-10:no_inbox"
        assert embedding["timestamp"] == AS_OF
        assert embedding["metadata"]["source"] == "backfill"
        assert embedding["metadata"]["exclude_inbox"] is True
        assert capture.call_args.kwargs["properties"]["source"] == "backfill"
        assert not UserActivitySummary.objects.for_team(self.team.id).exists()
        assert not UserActivitySummaryVersion.objects.for_team(self.team.id).exists()

    def test_a_dry_run_counts_builds_without_a_model_call(self) -> None:
        self._changes(self.team, self.user, 3)

        with patch(GATEWAY, side_effect=AssertionError("model called")):
            plan = plan_backfill(self._jobs(1) + self._jobs(40)[-1:], BackfillOptions())

        assert (plan.jobs, plan.builds) == (2, 1)
        assert plan.max_cost_usd == max_update_cost_usd()

    def test_the_cost_cap_stops_the_run_between_batches(self) -> None:
        self._changes(self.team, self.user, 3)
        llm = FakeLLM([ANSWER, ANSWER, ANSWER, ANSWER])
        with (
            patch(GATEWAY, return_value=llm),
            patch("posthog.api.embedding_worker.emit_embedding_request"),
            patch.object(tick, "ph_background_capture", return_value=MagicMock()),
        ):
            result = run_backfill(self._jobs(4), BackfillOptions(), max_cost_usd=1e-9)

        assert (result.attempted, result.stopped_at_cost_cap) == (1, True)
        assert len(llm.requests) == 1
