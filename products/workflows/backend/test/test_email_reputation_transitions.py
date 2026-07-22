from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from parameterized import parameterized

from products.workflows.backend.models import EmailReputationSnapshot
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.tasks.email_reputation import check_email_reputation_transitions

WEBHOOK_URL = "https://hooks.slack.example/services/T000/B000/XXX"


@override_settings(EMAIL_REPUTATION_SLACK_WEBHOOK_URL=WEBHOOK_URL)
class TestCheckEmailReputationTransitions(BaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()

    def _snapshot(self, state: str, evaluated_at: datetime) -> None:
        EmailReputationSnapshot(
            team=self.team,
            hog_flow=None,
            scope=EmailReputationSnapshot.Scope.TEAM,
            state=state,
            bounce_rate=0.06,
            complaint_rate=0.002,
            emails_sent=5000,
            evaluated_at=evaluated_at,
        ).save()

    def _run(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        with (
            patch("products.workflows.backend.tasks.email_reputation.send_email_reputation_degraded") as email_task,
            patch("products.workflows.backend.tasks.email_reputation.create_notification") as notification,
            patch("products.workflows.backend.tasks.email_reputation.requests.post") as slack_post,
        ):
            slack_post.return_value.raise_for_status = MagicMock()
            check_email_reputation_transitions()
        return email_task, notification, slack_post

    @parameterized.expand(
        [
            ("healthy_to_warning", "healthy", "warning", False, True, False),
            ("no_previous_to_warning", None, "warning", False, True, False),
            ("insufficient_data_to_warning", "insufficient_data", "warning", False, True, False),
            ("warning_to_critical", "warning", "critical", False, True, True),
            ("no_previous_to_critical", None, "critical", False, True, True),
            ("critical_persists_unsuspended", "critical", "critical", False, False, True),
            ("critical_persists_suspended", "critical", "critical", True, False, False),
            ("warning_persists", "warning", "warning", False, False, False),
            ("recovered_to_healthy", "critical", "healthy", False, False, False),
        ]
    )
    def test_transition_side_effects(
        self,
        _name: str,
        previous_state: str | None,
        latest_state: str,
        suspended: bool,
        expect_customer_notice: bool,
        expect_slack: bool,
    ) -> None:
        now = timezone.now()
        if previous_state is not None:
            self._snapshot(previous_state, now - timedelta(days=1))
        self._snapshot(latest_state, now - timedelta(hours=1))
        if suspended:
            TeamWorkflowsConfig.objects.update_or_create(team=self.team, defaults={"email_sending_suspended_at": now})

        email_task, notification, slack_post = self._run()

        assert email_task.delay.called == expect_customer_notice
        assert notification.called == expect_customer_notice
        assert slack_post.called == expect_slack
        if expect_customer_notice:
            assert email_task.delay.call_args.kwargs["team_id"] == self.team.id
            assert email_task.delay.call_args.kwargs["state"] == latest_state
        if expect_slack:
            assert slack_post.call_args.args[0] == WEBHOOK_URL

    def test_rerun_is_idempotent_per_snapshot(self):
        now = timezone.now()
        self._snapshot("healthy", now - timedelta(days=1))
        self._snapshot("warning", now - timedelta(hours=1))

        first_email_task, _, _ = self._run()
        second_email_task, second_notification, _ = self._run()

        assert first_email_task.delay.call_count == 1
        assert second_email_task.delay.call_count == 0
        assert second_notification.call_count == 0

    def test_new_snapshot_is_processed_after_earlier_one_was_marked(self):
        now = timezone.now()
        self._snapshot("warning", now - timedelta(days=1))
        self._run()

        self._snapshot("critical", now - timedelta(hours=1))
        email_task, _, slack_post = self._run()

        assert email_task.delay.call_count == 1
        assert slack_post.call_count == 1

    @override_settings(EMAIL_REPUTATION_SLACK_WEBHOOK_URL="")
    def test_missing_webhook_skips_slack_without_failing(self):
        self._snapshot("critical", timezone.now() - timedelta(hours=1))

        email_task, _, slack_post = self._run()

        assert slack_post.called is False
        # Customer notice still goes out; only the internal alert is skipped
        assert email_task.delay.call_count == 1
