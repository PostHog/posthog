import os
import importlib
from datetime import datetime, timedelta

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.instance_setting import set_instance_setting
from posthog.models.organization import OrganizationMembership
from posthog.settings import ses as ses_settings
from posthog.tasks.test.utils_email_tests import mock_email_messages
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
        # The detector reads whole clock hours and excludes the current partial hour, so seeds
        # default to the previous hour (see _seed). Pinned late in the hour so relative offsets in
        # individual tests stay inside the hour they aim for. Keeping the date today, rather than
        # an absolute one, avoids drifting out of any window.
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
        instance: str | None = None,
    ) -> None:
        # The previous hour by default: the detector reads complete hours only, so a seed in the
        # current (partial) hour is invisible to it.
        timestamp = at or self.now - timedelta(hours=1)
        # app_metrics2 keys rows on (…, instance_id, toStartOfHour(timestamp), …), so two seeds in
        # the same clock hour would collapse into one row and keep just one of the timestamps.
        # A distinct instance per call keeps them separate whatever time the suite runs at.
        self._seed_count += 1
        instance_id = instance or f"instance-{self._seed_count}"
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

    def _unenforced(self, enforced: bool):
        if enforced:
            return override_settings(WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS=frozenset({str(self.flow.id)}))
        return override_settings(WORKFLOW_EMAIL_AUTO_PAUSE_ENABLED=False)

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

    @patch(
        "products.workflows.backend.models.hog_flow_batch_job.hog_flow_batch_job.create_batch_hog_flow_job_invocation"
    )
    def test_breach_split_across_batch_jobs_is_still_discovered(self, _mock_dispatch):
        # Each batch job sits under the per-source volume gates, so per-source discovery gating
        # would never surface the team even though the workflow's aggregate breaches the 1h rule.
        job_1 = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.flow)
        job_2 = HogFlowBatchJob.objects.create(team=self.team, hog_flow=self.flow)
        self._seed(source_id=str(job_1.id), sent=100, complaints=3)
        self._seed(source_id=str(job_2.id), sent=100, complaints=3)

        applied, _ = self._sweep()

        assert [decision.hog_flow_id for decision in applied] == [str(self.flow.id)]

    def test_a_failing_worker_reload_does_not_drop_the_admin_email(self):
        # The reload callback runs before the email callback. Without robust registration, its
        # failure stops the remaining callbacks: the pause commits, the admins are never told, and
        # later runs skip the paused workflow, so the email is never retried.
        self._seed(sent=400, complaints=8)
        with (
            patch(
                "products.workflows.backend.services.workflow_email_health.send_workflow_email_sending_paused"
            ) as paused_email,
            patch("products.workflows.backend.services.workflow_email_health.send_workflow_email_sending_warning"),
            patch(
                "products.workflows.backend.services.workflow_email_health.reload_hog_flows_on_workers",
                side_effect=Exception("redis down"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            applied = sweep_workflow_email_health(now=self.now)

        assert len(applied) == 1
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None
        assert paused_email.delay.call_count == 1

    def test_window_starts_after_the_last_resume(self):
        # Breach feedback two hours back, resume a few minutes later in the same hour: the clamp
        # starts at the next full hour, so the pre-resume feedback is out of scope.
        self._seed(sent=400, complaints=8, at=self.now - timedelta(hours=2))
        self.flow.email_sending_resumed_at = self.now - timedelta(hours=2) + timedelta(minutes=5)
        self.flow.save(update_fields=["email_sending_resumed_at"])

        applied, _ = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None

    def test_feedback_after_a_resume_still_trips(self):
        self._seed(sent=400, complaints=8, at=self.now - timedelta(hours=2))
        self._seed(sent=400, complaints=8, at=self.now - timedelta(hours=1))
        self.flow.email_sending_resumed_at = self.now - timedelta(hours=2) + timedelta(minutes=5)
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

    def test_a_breach_spread_across_workflows_pauses_each_workflow_at_the_rate(self):
        spreading = HogFlow.objects.create(name="Second blast", team=self.team)
        under_the_rate = HogFlow.objects.create(name="Onboarding", team=self.team)
        self._seed(sent=150, hard_bounces=30)
        self._seed(source_id=str(spreading.id), sent=150, hard_bounces=30)
        self._seed(source_id=str(under_the_rate.id), sent=150, hard_bounces=5)

        applied, _ = self._sweep()

        assert sorted(decision.hog_flow_id for decision in applied) == sorted([str(self.flow.id), str(spreading.id)])
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_reason == (
            "Emails to addresses that do not exist across this project's workflows passed the pause limit in "
            "the last hour. This workflow sent 150 emails in that time, and 30 of the emails to addresses "
            "that do not exist came from it."
        )
        under_the_rate.refresh_from_db()
        assert under_the_rate.email_sending_paused_at is None
        assert under_the_rate.email_sending_warned_at is None

    def test_complaints_spread_across_workflows_pause_and_warn_no_workflow(self):
        spreading = HogFlow.objects.create(name="Second blast", team=self.team)
        self._seed(sent=150, complaints=4)
        self._seed(source_id=str(spreading.id), sent=150, complaints=4)

        self._sweep()

        for flow in (self.flow, spreading):
            flow.refresh_from_db()
            assert (flow.email_sending_paused_at, flow.email_sending_warned_at) == (None, None)

    @parameterized.expand(
        [
            ("exempt_breach_beside_a_quiet_sibling", (300, 60), (8, 1), ["exempt"], []),
            ("sibling_breach_beside_a_quiet_exempt_workflow", (1, 1), (300, 60), ["sibling"], ["sibling"]),
        ]
    )
    def test_an_exempt_workflow_is_judged_only_on_its_own_sends(
        self,
        _name: str,
        exempt_seed: tuple[int, int],
        sibling_seed: tuple[int, int],
        decided: list[str],
        paused: list[str],
    ):
        sibling = HogFlow.objects.create(name="Second blast", team=self.team)
        self._seed(sent=exempt_seed[0], hard_bounces=exempt_seed[1])
        self._seed(source_id=str(sibling.id), sent=sibling_seed[0], hard_bounces=sibling_seed[1])
        names = {str(self.flow.id): "exempt", str(sibling.id): "sibling"}

        with self._unenforced(True):
            decisions = find_workflow_email_pauses(now=self.now)
            self._sweep()

        assert [names[decision.hog_flow_id] for decision in decisions] == decided
        for flow in (self.flow, sibling):
            flow.refresh_from_db()
        assert [names[str(flow.id)] for flow in (self.flow, sibling) if flow.email_sending_paused_at] == paused
        assert (self.flow.email_sending_paused_at, self.flow.email_sending_warned_at) == (None, None)

    @parameterized.expand(
        [
            ("transactional_breach_alone", ["transactional"], (300, 60), None, [], [("warning", True, False)]),
            (
                "transactional_breach_beside_a_quiet_sibling",
                ["transactional"],
                (300, 60),
                (8, 1),
                [],
                [("warning", True, False)],
            ),
            (
                "sibling_breach_beside_a_quiet_transactional_workflow",
                ["transactional"],
                (1, 1),
                (300, 60),
                ["sibling"],
                [("paused", False, True)],
            ),
            (
                "one_marketing_step_makes_it_pausable",
                ["transactional", "marketing"],
                (300, 60),
                None,
                ["own"],
                [("paused", False, True)],
            ),
            (
                "a_generic_email_template_step_makes_it_pausable",
                ["transactional", "generic"],
                (300, 60),
                None,
                ["own"],
                [("paused", False, True)],
            ),
            (
                "a_legacy_sms_step_on_the_email_template_makes_it_pausable",
                ["transactional", "sms_on_email_template"],
                (300, 60),
                None,
                ["own"],
                [("paused", False, True)],
            ),
            (
                "a_step_with_a_malformed_config_is_skipped",
                ["transactional", "malformed"],
                (300, 60),
                None,
                [],
                [("warning", True, False)],
            ),
        ]
    )
    @patch("posthog.tasks.email.EmailMessage")
    def test_a_transactional_workflow_is_warned_instead_of_paused(
        self,
        _name: str,
        categories: list[str],
        own_seed: tuple[int, int],
        sibling_seed: tuple[int, int] | None,
        paused: list[str],
        emails: list[tuple[str, bool, bool]],
        MockEmailMessage: MagicMock,
    ):
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        sent_emails = mock_email_messages(MockEmailMessage)
        other_steps: dict[str, dict[str, object]] = {
            "generic": {"type": "function", "config": {"template_id": "template-email"}},
            "sms_on_email_template": {"type": "function_sms", "config": {"template_id": "template-email"}},
            "malformed": {"type": "function", "config": "not an object"},
        }
        self.flow.actions = [
            {"id": f"step_{index}", **other_steps[category]}
            if category in other_steps
            else {"id": f"step_{index}", "type": "function_email", "config": {"message_category_type": category}}
            for index, category in enumerate(categories)
        ]
        self.flow.save()
        sibling = HogFlow.objects.create(name="Second blast", team=self.team)
        names = {str(self.flow.id): "own", str(sibling.id): "sibling"}
        self._seed(sent=own_seed[0], hard_bounces=own_seed[1])
        if sibling_seed is not None:
            self._seed(source_id=str(sibling.id), sent=sibling_seed[0], hard_bounces=sibling_seed[1])

        with (
            patch("products.workflows.backend.services.workflow_email_health.reload_hog_flows_on_workers"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            sweep_workflow_email_health(now=self.now)

        for flow in (self.flow, sibling):
            flow.refresh_from_db()
        assert [names[str(flow.id)] for flow in (self.flow, sibling) if flow.email_sending_paused_at] == paused
        assert [
            (
                message.template_name.removeprefix("workflow_email_sending_"),
                "we don't pause it automatically" in message.html_body,
                "never open anything" in message.html_body,
            )
            for message in sent_emails
            if message.send.call_count == 1
        ] == emails

    def test_a_project_pause_counts_late_bounces_apart_from_sends(self):
        sibling = HogFlow.objects.create(name="Second blast", team=self.team)
        self._seed(sent=50, at=self.now - timedelta(hours=2))
        self._seed(sent=10, hard_bounces=15)
        self._seed(source_id=str(sibling.id), sent=190, hard_bounces=10)

        applied, _ = self._sweep()

        assert [decision.hog_flow_id for decision in applied] == [str(self.flow.id)]
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_reason == (
            "Emails to addresses that do not exist across this project's workflows passed the pause limit in "
            "the last hour. This workflow sent 10 emails in that time, and 15 of the emails to addresses "
            "that do not exist came from it."
        )

    def test_a_warn_band_spread_across_workflows_warns_each_workflow(self):
        spreading = HogFlow.objects.create(name="Second blast", team=self.team)
        self._seed(sent=150, hard_bounces=12)
        self._seed(source_id=str(spreading.id), sent=150, hard_bounces=12)

        applied, _ = self._sweep()

        assert applied == []
        for flow in (self.flow, spreading):
            flow.refresh_from_db()
            assert flow.email_sending_paused_at is None
            assert flow.email_sending_warned_at == self.now

    @parameterized.expand(
        [
            ("own_rate_past_the_pause_line", [(0, 2, 600, 0, 0), (0, 1, 300, 0, 40)], {}, []),
            ("project_rate_past_the_pause_line", [(0, 2, 450, 0, 0), (0, 1, 150, 0, 30), (1, 1, 150, 0, 10)], {}, []),
            ("rate_that_rounds_to_the_pause_line", [(0, 2, 1000, 0, 0), (0, 1, 501, 5, 0)], {}, []),
            (
                "rate_that_rounds_to_an_unrounded_pause_line",
                [(0, 2, 1000, 0, 0), (0, 1, 501, 5, 0)],
                {"WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_1H": 0.01004},
                [],
            ),
            (
                "rate_that_shows_as_a_pause_line_rounded_half_up",
                [(0, 1, 10_000, 30, 0)],
                {"WORKFLOW_EMAIL_AUTO_PAUSE_COMPLAINT_RATE_24H": 0.00305},
                [],
            ),
            (
                "complaints_past_the_line_fall_through_to_bounces",
                [(0, 2, 550, 0, 0), (0, 1, 300, 5, 28)],
                {},
                [
                    (
                        0,
                        "Emails to addresses that do not exist reached 9.33% of the 300 emails this workflow "
                        "sent in the last hour.",
                        "10%",
                    )
                ],
            ),
            (
                "project_rate_under_the_line",
                [(0, 1, 100, 0, 15), (1, 1, 150, 0, 6)],
                {},
                [
                    (
                        0,
                        "Emails to addresses that do not exist reached 8.4% of the 250 emails this project's "
                        "workflows sent in the last hour. This workflow sent 100 of those emails, and 15 of the "
                        "emails to addresses that do not exist came from it.",
                        "10%",
                    )
                ],
            ),
        ]
    )
    def test_a_warning_names_a_rate_under_the_pause_line(
        self,
        _name: str,
        seeds: list[tuple[int, int, int, int, int]],
        pause_rates: dict[str, float],
        warned: list[tuple[int, str, str]],
    ):
        flows = [self.flow, HogFlow.objects.create(name="Second blast", team=self.team)]
        for flow_index, hours_ago, sent, complaints, hard_bounces in seeds:
            self._seed(
                source_id=str(flows[flow_index].id),
                sent=sent,
                complaints=complaints,
                hard_bounces=hard_bounces,
                at=self.now - timedelta(hours=hours_ago),
            )

        with override_settings(**pause_rates):
            self._sweep()

        flow_ids = [str(flow.id) for flow in flows]
        delivered = [call.kwargs for call in self.warning_email.call_args_list]
        assert [
            (flow_ids.index(sent["hog_flow_id"]), sent["reason"], sent["pause_rate"]) for sent in delivered
        ] == warned
        for flow in flows:
            flow.refresh_from_db()
        assert [flow.email_sending_paused_at for flow in flows] == [None, None]

    @parameterized.expand(
        [
            ("late_bounces_after_a_large_send_the_day_before", [(0, 30, 100_000, 0), (0, 1, 2000, 120)], None, []),
            ("steady_sender", [(0, 30, 2000, 0), (0, 1, 2000, 120)], None, [0]),
            ("late_bounces_in_the_hour_after_a_large_send", [(0, 2, 3000, 0), (0, 1, 300, 40)], None, []),
            (
                "project_breach_after_a_sibling_sent_a_large_batch",
                [(0, 1, 150, 30), (1, 1, 150, 30), (2, 1, 150, 5), (2, 2, 3000, 0)],
                None,
                [],
            ),
            (
                "project_breach_after_a_quiet_sibling_sent_a_large_batch",
                [(0, 1, 150, 30), (1, 1, 150, 30), (2, 2, 3000, 0)],
                None,
                [0, 1],
            ),
            (
                "project_breach_after_a_clean_sibling_sent_a_large_batch",
                [(0, 1, 150, 30), (1, 1, 150, 30), (2, 1, 1, 0), (2, 2, 3000, 0)],
                None,
                [0, 1],
            ),
            (
                "project_breach_after_a_bouncing_sibling_sent_a_large_batch",
                [(0, 1, 150, 30), (1, 1, 150, 30), (2, 1, 1, 1), (2, 2, 3000, 0)],
                None,
                [],
            ),
            (
                "project_breach_from_late_bounces_beside_a_clean_sibling",
                [(0, 1, 150, 15), (1, 1, 0, 20), (1, 2, 300, 0), (2, 1, 150, 0), (2, 2, 1000, 0)],
                None,
                [],
            ),
            ("late_bounces_after_a_resume", [(0, 2, 5000, 0), (0, 1, 1200, 80)], 2, []),
        ]
    )
    def test_feedback_is_judged_against_the_sends_of_the_window_before(
        self,
        _name: str,
        seeds: list[tuple[int, int, int, int]],
        resumed_hours_ago: int | None,
        paused: list[int],
    ):
        flows = [
            self.flow,
            HogFlow.objects.create(name="Second blast", team=self.team),
            HogFlow.objects.create(name="Onboarding", team=self.team),
        ]
        for flow_index, hours_ago, sent, hard_bounces in seeds:
            self._seed(
                source_id=str(flows[flow_index].id),
                sent=sent,
                hard_bounces=hard_bounces,
                at=self.now - timedelta(hours=hours_ago),
            )
        if resumed_hours_ago is not None:
            self.flow.email_sending_resumed_at = self.now - timedelta(hours=resumed_hours_ago, minutes=-5)
            self.flow.save(update_fields=["email_sending_resumed_at"])

        applied, _ = self._sweep()

        assert sorted(decision.hog_flow_id for decision in applied) == sorted(str(flows[i].id) for i in paused)

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

    @parameterized.expand([("dry_run", False), ("exempt_workflow", True)])
    def test_unenforced_workflow_is_not_warned(self, _name: str, enforced: bool):
        self._seed(sent=10000, complaints=20)

        with self._unenforced(enforced):
            self._sweep()

        self.flow.refresh_from_db()
        assert self.flow.email_sending_warned_at is None

    @parameterized.expand([("dry_run", False), ("exempt", True)])
    def test_unenforced_workflow_counts_the_breach_but_writes_nothing(self, mode: str, enforced: bool):
        self._seed(sent=400, complaints=8)
        labels = {"signal": "complaint", "window": "1h", "mode": mode, "scope": "workflow"}
        counted_before = REGISTRY.get_sample_value("workflow_email_auto_pause_total", labels) or 0

        with self._unenforced(enforced):
            applied, _ = self._sweep()

        assert applied == []
        assert REGISTRY.get_sample_value("workflow_email_auto_pause_total", labels) == counted_before + 1
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None
        assert self.flow.email_sending_paused_reason == ""

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
                    hog_flow_name=self.flow.name or "",
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

    def test_a_stale_instance_cannot_clear_a_staff_pause_placed_in_between(self):
        # The API loads the workflow before calling resume. A staff pause landing between that read
        # and the write must win: the resume re-reads under lock, sees "staff", and refuses.
        self._seed(sent=400, complaints=8)
        self._sweep()
        stale = HogFlow.objects.get(pk=self.flow.pk)
        assert stale.email_sending_paused_by == "auto"
        HogFlow.objects.filter(pk=self.flow.pk).update(email_sending_paused_by=PAUSED_BY_STAFF)

        try:
            resume_workflow_email_sending(stale)
            raise AssertionError("stale customer resume must not clear a staff pause")
        except StaffPausedError:
            pass
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None

    def test_a_resume_hour_shared_with_old_feedback_is_not_judged(self):
        # Production stamps one instance id (the action id) on every row, so pre-resume and
        # post-resume feedback in the resume's own hour merge into a single hourly row. That mixed
        # hour is excluded by the clamp: the detector must not re-trip on it, and only a later full
        # hour of fresh feedback counts.
        hour = self.now - timedelta(hours=1)
        self._seed(sent=400, complaints=8, at=hour, instance="shared-action-id")
        self._seed(sent=400, complaints=8, at=hour + timedelta(minutes=8), instance="shared-action-id")
        self.flow.email_sending_resumed_at = hour + timedelta(minutes=4)
        self.flow.save(update_fields=["email_sending_resumed_at"])

        applied, _ = self._sweep()

        assert applied == []
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is None

    def test_a_repeat_pause_is_not_customer_resumable(self):
        # Resume-polling must not keep a spammy workflow sending: a pause landing inside the repeat
        # window of the previous resume needs staff. An old resume outside the window changes nothing.
        self.flow.email_sending_resumed_at = self.now - timedelta(days=1)
        self.flow.save(update_fields=["email_sending_resumed_at"])
        self._seed(sent=400, complaints=8)
        self._sweep()
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_by == "auto"

        try:
            resume_workflow_email_sending(self.flow)
            raise AssertionError("a repeat pause must not be customer-resumable")
        except StaffPausedError:
            pass
        assert resume_workflow_email_sending(self.flow, actor=PAUSED_BY_STAFF) is True

    def test_a_pause_long_after_the_last_resume_stays_customer_resumable(self):
        self.flow.email_sending_resumed_at = self.now - timedelta(days=30)
        self.flow.save(update_fields=["email_sending_resumed_at"])
        self._seed(sent=400, complaints=8)
        self._sweep()
        self.flow.refresh_from_db()
        assert self.flow.email_sending_paused_at is not None

        assert resume_workflow_email_sending(self.flow) is True

    def test_resume_is_a_no_op_when_not_paused(self):
        assert resume_workflow_email_sending(self.flow) is False
        self.flow.refresh_from_db()
        assert self.flow.email_sending_resumed_at is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("", frozenset()),
        (" 01A16477-CF0E-0000-FCD4-AB12E88F3D00 ,", frozenset({"01a16477-cf0e-0000-fcd4-ab12e88f3d00"})),
    ],
)
def test_exempt_workflow_ids_from_the_environment_match_stored_ids(raw: str, expected: frozenset[str]):
    try:
        with patch.dict(os.environ, {"WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS": raw}):
            assert importlib.reload(ses_settings).WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS == expected
    finally:
        importlib.reload(ses_settings)


@pytest.mark.parametrize(
    "raw",
    ["not-a-workflow-id", "1_A16477-CF0E-0000-FCD4-AB12E88F3D00", "01a16477-cf0e-0000-fcd4-ab12e88f3d00,garbage"],
)
def test_a_malformed_exempt_workflow_id_stops_startup(raw: str):
    try:
        with patch.dict(os.environ, {"WORKFLOW_EMAIL_AUTO_PAUSE_EXEMPT_WORKFLOW_IDS": raw}):
            with pytest.raises(ValueError):
                importlib.reload(ses_settings)
    finally:
        importlib.reload(ses_settings)
