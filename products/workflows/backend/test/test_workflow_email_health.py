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
    PAUSED_BY_STAFF,
    StaffPausedError,
    find_workflow_email_pauses,
    pause_workflow_email_sending,
    resume_workflow_email_sending,
    sweep_workflow_email_health,
)

AUTO_PAUSE_ON = {"WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED": True}


@override_settings(**AUTO_PAUSE_ON)
class TestWorkflowEmailHealthDetector(ClickhouseTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        # Pinned late in the hour so every seed these tests place (down to 40 minutes back) lands
        # in one clock hour. app_metrics2 buckets its sort key by hour, so that is the arrangement
        # most likely to collapse two seeds into a single row and lose one of the timestamps.
        # Keeping the date today, rather than an absolute one, avoids drifting out of any window.
        self.now = timezone.now().replace(minute=50, second=0, microsecond=0)
        self._seed_count = 0
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
        # app_metrics2 keys rows on (…, instance_id, toStartOfHour(timestamp), …), so two seeds in
        # the same clock hour would collapse into one row and keep just one of the timestamps.
        # A distinct instance per call keeps them separate whatever time the suite runs at.
        self._seed_count += 1
        instance_id = f"instance-{self._seed_count}"
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
                    instance_id=instance_id,
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
            patch(
                "products.workflows.backend.services.workflow_email_health.send_workflow_email_sending_warning"
            ) as warning_email,
            self.captureOnCommitCallbacks(execute=True),
        ):
            applied = sweep_workflow_email_health(now=self.now)
        self.warning_email = warning_email.delay
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
        # The rate is over the warn band too; the pause outranks the warning, so only one email.
        assert self.warning_email.call_count == 0

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
        self._seed(
            sent=counts.get("sent", 0),
            complaints=counts.get("complaints", 0),
            hard_bounces=counts.get("hard_bounces", 0),
        )

        applied, paused_email = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert paused_email.call_count == 0
        assert self.warning_email.call_count == 0

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

    def test_warn_band_warns_without_pausing(self):
        # 0.2% complaints over 24h: above the 0.15% warn rate, below the 0.3% pause rate.
        self._seed(sent=10000, complaints=20)

        applied, paused_email = self._sweep()

        assert applied == []
        assert paused_email.call_count == 0
        assert self.warning_email.call_count == 1
        assert self.warning_email.call_args.kwargs["hog_flow_id"] == str(self.flow.id)
        assert self.warning_email.call_args.kwargs["pause_rate"] == "0.3%"
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.flow.email_sending_warned_at is not None

    def test_warning_is_not_repeated_within_the_cooldown(self):
        self._seed(sent=10000, complaints=20)
        self.flow.email_sending_warned_at = self.now - timedelta(days=1)
        self.flow.save(update_fields=["email_sending_warned_at"])

        self._sweep()

        assert self.warning_email.call_count == 0

    def test_warning_repeats_once_the_cooldown_passed(self):
        self._seed(sent=10000, complaints=20)
        self.flow.email_sending_warned_at = self.now - timedelta(days=8)
        self.flow.save(update_fields=["email_sending_warned_at"])

        self._sweep()

        assert self.warning_email.call_count == 1

    def test_a_failing_writer_does_not_abort_the_other_decisions(self):
        # One workflow breaches (a pause) and another sits in the warn band. The pause loop runs
        # before the warning loop, so a raising pause writer that was not isolated would take the
        # warning down with it.
        self._seed(sent=400, complaints=8)
        other = HogFlow.objects.create(name="Newsletter", team=self.team)
        self._seed(source_id=str(other.id), sent=10000, complaints=20)

        with patch(
            "products.workflows.backend.services.workflow_email_health.apply_pause",
            side_effect=RuntimeError("worker reload publish failed"),
        ):
            applied, _ = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.warning_email.call_count == 1
        assert self.warning_email.call_args.kwargs["hog_flow_id"] == str(other.id)

    @override_settings(WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED=False)
    def test_dry_run_does_not_warn(self):
        self._seed(sent=10000, complaints=20)

        self._sweep()

        assert self.warning_email.call_count == 0
        self.flow.refresh_from_db()
        assert self.flow.email_sending_warned_at is None

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

        # A fresh instance rather than refresh_from_db: mypy narrows the attribute to datetime at
        # the assignment above and treats the is-None assert on the same instance as unreachable.
        refreshed = HogFlow.objects.get(pk=self.flow.pk)
        assert refreshed.email_sending_paused_at is None
        assert refreshed.email_sending_paused_reason == ""
        assert refreshed.email_sending_resumed_at is not None

    def test_a_detector_pause_is_customer_resumable_and_a_staff_pause_is_not(self):
        self._seed(sent=400, complaints=8)
        self._sweep()
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_by == "auto"
        assert resume_workflow_email_sending(self.flow) is True

        with patch("products.workflows.backend.services.workflow_email_health.send_workflow_email_sending_paused"):
            with self.captureOnCommitCallbacks(execute=True):
                pause_workflow_email_sending(
                    team_id=self.team.pk,
                    hog_flow_id=str(self.flow.id),
                    hog_flow_name=self.flow.name,
                    reason="Staff pause",
                    paused_by=PAUSED_BY_STAFF,
                )
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_by == "staff"
        try:
            resume_workflow_email_sending(self.flow)
            raise AssertionError("customer resume of a staff pause must raise")
        except StaffPausedError:
            pass
        assert resume_workflow_email_sending(self.flow, actor=PAUSED_BY_STAFF) is True
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_by == ""

    def test_resume_is_a_no_op_when_not_paused(self):
        assert resume_workflow_email_sending(self.flow) is False
        self.flow.refresh_from_db()
        assert self.flow.email_sending_resumed_at is None
