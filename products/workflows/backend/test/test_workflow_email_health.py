from datetime import datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from posthog.test.fixtures import create_app_metric2

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job import HogFlowBatchJob
from products.workflows.backend.services.workflow_email_health import (
    find_workflow_email_pauses,
    resume_workflow_email_sending,
    sweep_workflow_email_health,
)

AUTO_PAUSE_ON = {"WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED": True}


@override_settings(**AUTO_PAUSE_ON)
class TestWorkflowEmailHealthDetector(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        self.now = timezone.now()
        self.flow = HogFlow.objects.create(name="Welcome email", team=self.team)

    def _seed(
        self,
        *,
        source_id: str | None = None,
        sent: int = 0,
        complaints: int = 0,
        hard_bounces: int = 0,
        at: datetime | None = None,
    ) -> None:
        timestamp = at or self.now - timedelta(minutes=5)
        for metric_name, count in (
            ("email_sent", sent),
            ("email_blocked", complaints),
            ("email_bounced_hard", hard_bounces),
        ):
            if count:
                create_app_metric2(
                    team_id=self.team.pk,
                    app_source="hog_flow",
                    app_source_id=source_id or str(self.flow.id),
                    metric_kind="email",
                    metric_name=metric_name,
                    count=count,
                    timestamp=timestamp,
                )

    def _sweep(self):
        with (
            patch(
                "products.workflows.backend.services.workflow_email_health.send_workflow_email_sending_paused"
            ) as paused_email,
            self.captureOnCommitCallbacks(execute=True),
        ):
            applied = sweep_workflow_email_health(now=self.now)
        return applied, paused_email.delay

    def test_complaint_breach_pauses_the_workflow_and_notifies(self):
        self._seed(sent=400, complaints=8)

        applied, paused_email = self._sweep()

        assert [decision.hog_flow_id for decision in applied] == [str(self.flow.id)]
        assert applied[0].threshold.signal == "complaint"
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None
        assert "Spam complaints reached 2%" in self.flow.email_sending_paused_reason
        assert paused_email.call_count == 1

    def test_hard_bounce_breach_pauses_the_workflow(self):
        self._seed(sent=400, hard_bounces=60)

        applied, _ = self._sweep()

        assert [decision.threshold.signal for decision in applied] == ["bounce"]
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None
        assert "addresses that do not exist reached 15%" in self.flow.email_sending_paused_reason

    @parameterized.expand(
        [
            # Rate is over the 1h complaint threshold, but too few sends to mean anything.
            ("complaints below the send gate", {"sent": 100, "complaints": 8}),
            # Enough sends, but a single complaint is noise rather than a pattern.
            ("complaints below the event gate", {"sent": 5000, "complaints": 4}),
            ("hard bounces below the send gate", {"sent": 100, "hard_bounces": 60}),
            ("hard bounces below the event gate", {"sent": 5000, "hard_bounces": 19}),
            # Both gates met, but the rate stays under every threshold in the table.
            ("rate under the threshold", {"sent": 20000, "complaints": 20, "hard_bounces": 60}),
        ]
    )
    def test_does_not_pause_below_the_thresholds(self, _name: str, counts: dict[str, int]):
        self._seed(**counts)

        applied, paused_email = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert paused_email.call_count == 0

    # Creating a HogFlowBatchJob fires a post_save signal that dispatches to the plugin server —
    # patched out like every other batch-job test, or the outbound HTTP attempt fails the test.
    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_batch_job_metrics_fold_into_the_parent_workflow(self, _mock_dispatch):
        # A batch send records its metrics under the batch job id, so without resolving the job back
        # to its parent this is the case the detector would miss entirely.
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.flow)
        self._seed(source_id=str(batch_job.id), sent=5000, complaints=60)

        applied, _ = self._sweep()

        assert [decision.hog_flow_id for decision in applied] == [str(self.flow.id)]
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_clean_batch_send_keeps_a_workflow_below_the_threshold(self, _mock_dispatch):
        # The discovery pass gates per source id, so counting only the rows it returns would read the
        # workflow-id row's 5% complaint rate and pause a workflow that is really at 0.1%.
        batch_job = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.flow)
        self._seed(sent=300, complaints=15)
        self._seed(source_id=str(batch_job.id), sent=20000, complaints=1)

        applied, _ = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None

    def test_window_starts_after_the_last_resume(self):
        self._seed(sent=400, complaints=8, at=self.now - timedelta(minutes=40))
        self.flow.email_sending_resumed_at = self.now - timedelta(minutes=20)
        self.flow.save(update_fields=["email_sending_resumed_at"])

        applied, _ = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None

    def test_feedback_after_a_resume_still_trips(self):
        self._seed(sent=400, complaints=8, at=self.now - timedelta(minutes=40))
        self._seed(sent=400, complaints=8, at=self.now - timedelta(minutes=5))
        self.flow.email_sending_resumed_at = self.now - timedelta(minutes=20)
        self.flow.save(update_fields=["email_sending_resumed_at"])

        applied, _ = self._sweep()

        assert [decision.hog_flow_id for decision in applied] == [str(self.flow.id)]

    def test_already_paused_workflow_is_not_paused_again(self):
        self._seed(sent=400, complaints=8)
        self.flow.email_sending_paused_at = self.now - timedelta(hours=2)
        self.flow.email_sending_paused_reason = "Earlier pause"
        self.flow.save(update_fields=["email_sending_paused_at", "email_sending_paused_reason"])

        applied, paused_email = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_reason == "Earlier pause"
        assert paused_email.call_count == 0

    @override_settings(WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED=False)
    def test_dry_run_finds_the_breach_but_writes_nothing(self):
        self._seed(sent=400, complaints=8)

        applied, paused_email = self._sweep()

        assert applied == []
        assert [decision.hog_flow_id for decision in find_workflow_email_pauses(now=self.now)] == [str(self.flow.id)]
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.flow.email_sending_paused_reason == ""
        assert paused_email.call_count == 0

    @override_settings(WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_1H=0.5)
    def test_thresholds_come_from_settings(self):
        self._seed(sent=400, complaints=8)

        applied, _ = self._sweep()

        assert applied == []

    def test_resume_clears_the_pause_and_stamps_the_resume_time(self):
        self.flow.email_sending_paused_at = self.now - timedelta(hours=1)
        self.flow.email_sending_paused_reason = "Spam complaints reached 2%."
        self.flow.save(update_fields=["email_sending_paused_at", "email_sending_paused_reason"])

        assert resume_workflow_email_sending(self.flow) is True

        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.flow.email_sending_paused_reason == ""
        assert self.flow.email_sending_resumed_at is not None

    def test_resume_is_a_no_op_when_not_paused(self):
        assert resume_workflow_email_sending(self.flow) is False
        self.flow.refresh_from_db()
        assert self.flow.email_sending_resumed_at is None
