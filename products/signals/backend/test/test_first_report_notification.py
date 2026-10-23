import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from celery.exceptions import Retry
from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.transactional_email import (
    TransactionalEmailDeliveryUncertain,
    TransactionalEmailRejected,
    TransactionalEmailRetryableError,
    send_transactional_email,
)

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.first_report_notification import (
    deliver_first_report_email,
    register_first_report_notification,
)
from products.signals.backend.first_report_notification_tasks import (
    dispatch_first_report_notification,
    sweep_first_report_notifications,
)
from products.signals.backend.models import SignalFirstReportNotification, SignalReport, SignalReportArtefact
from products.signals.backend.report_access import may_read_reports

MODULE = "products.signals.backend.first_report_notification"
TASK_MODULE = "products.signals.backend.first_report_notification_tasks"


@time_machine.travel("2026-01-15T12:00:00Z", tick=False)
@override_settings(SITE_URL="https://app.example.com")
class TestFirstReportNotification(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.template_id = uuid4()
        self.enterContext(
            override_settings(
                POSTHOG_HOST="https://us.posthog.com",
                POSTHOG_PROJECT_ID=123456789,
                POSTHOG_TRANSACTIONAL_EMAIL_API_KEY="phs_fake_transactional_key",
            )
        )
        self.enterContext(patch(f"{MODULE}.SIGNALS_FIRST_REPORT_EMAIL_TEMPLATE_ID", str(self.template_id)))
        self.enterContext(patch(f"{MODULE}.is_cloud", return_value=True))
        self.enterContext(patch(f"{TASK_MODULE}.is_cloud", return_value=True))
        self.email_flag = self.enterContext(patch(f"{MODULE}.team_first_report_email_enabled", return_value=True))
        response = Mock(status_code=202)
        response.json.return_value = {"message_id": "example-message-id"}
        self.post = self.enterContext(patch("posthog.transactional_email.requests.post", return_value=response))
        self.send = self.enterContext(patch(f"{MODULE}.send_transactional_email", wraps=send_transactional_email))
        register_first_report_notification(team=self.team, user=self.user)

    def report(self, **overrides: object) -> SignalReport:
        return SignalReport.objects.create(
            **{
                "team": self.team,
                "status": SignalReport.Status.READY,
                "title": "Checkout errors increased",
                "summary": "An actionable report.",
                "signal_count": 1,
                "total_weight": 1,
                "first_visible_at": timezone.now(),
                "latest_actionability": "immediately_actionable",
                "latest_already_addressed": False,
                **overrides,
            }
        )

    def notification(self) -> SignalFirstReportNotification:
        return SignalFirstReportNotification.objects.for_team(self.team.id).get()

    @parameterized.expand(
        [
            (
                "summary_lead",
                "Users cannot accept expired invitations.\n\n## Evidence\nMore details.",
                "Users cannot accept expired invitations.",
                "P1",
            ),
            ("long_summary_without_priority", "x" * 400, "x" * 319 + "…", ""),
            (
                "markdown_summary",
                "Signups **dropped** after the [pricing change](https://example.com/pricing).\n"
                "[The daily signups chart](chart:daily-signups) shows the drop.\n\n## Evidence\nMore details.",
                "Signups dropped after the pricing change. The daily signups chart shows the drop.",
                "P2",
            ),
        ]
    )
    @time_machine.travel("2026-01-15T12:01:00Z", tick=False)
    def test_first_report_targets_activator_once_per_project(
        self, _name: str, summary: str, expected_summary: str, priority: str
    ) -> None:
        first = self.report(first_visible_at=timezone.now() - timedelta(seconds=1), summary=summary)
        if priority:
            SignalReportArtefact.objects.create(
                team=self.team,
                report=first,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
                content=json.dumps({"priority": priority, "explanation": "The invitation flow is blocked."}),
            )
        self.report()
        other_user = User.objects.create_and_join(self.organization, "other@example.com", None)
        register_first_report_notification(team=self.team, user=other_user)

        deliver_first_report_email(self.team.id)
        deliver_first_report_email(self.team.id)

        self.send.assert_called_once_with(
            str(self.template_id),
            to=self.user.email,
            distinct_id=str(self.user.distinct_id),
            message_data={
                "project_id": self.team.id,
                "report_id": str(first.id),
                "report_title": first.title,
                "report_summary": expected_summary,
                "report_priority": priority,
                "report_url": f"https://app.example.com/project/{self.team.id}/inbox/reports/{first.id}?link_source=first_report_email",
                "activation_id": str(self.notification().id),
            },
        )
        assert self.notification().queued_at is not None
        assert self.notification().message_id == "example-message-id"
        assert self.post.call_args.args[0] == (
            f"https://us.posthog.com/api/projects/123456789/messaging_templates/{self.template_id}/send/"
        )
        other_team = Team.objects.create(organization=self.organization, name="Another project")
        register_first_report_notification(team=other_team, user=self.user)
        self.report(team=other_team)
        deliver_first_report_email(other_team.id)
        assert self.send.call_count == 2

    @parameterized.expand(
        [
            ("researching", {"status": SignalReport.Status.IN_PROGRESS}),
            ("suppressed", {"status": SignalReport.Status.SUPPRESSED}),
            ("failed", {"status": SignalReport.Status.FAILED}),
            ("needs_input", {"status": SignalReport.Status.PENDING_INPUT}),
            ("not_actionable", {"latest_actionability": "not_actionable"}),
            ("already_addressed", {"latest_already_addressed": True}),
            ("not_judged", {"latest_actionability": None}),
            ("empty", {"summary": ""}),
            ("never_visible", {"first_visible_at": None}),
            ("before_activation", {"first_visible_at": datetime(2026, 1, 14, tzinfo=UTC)}),
        ]
    )
    def test_waits_for_an_eligible_report(self, _name: str, overrides: dict[str, object]) -> None:
        self.report(**overrides)
        deliver_first_report_email(self.team.id)
        self.send.assert_not_called()
        assert self.notification().send_started_at is None
        assert self.notification().cancelled_at is None

    @parameterized.expand([("inactive",), ("removed",), ("no_email",), ("no_access",), ("deleted",)])
    def test_does_not_substitute_another_recipient(self, reason: str) -> None:
        self.report()
        if reason == "inactive":
            self.user.is_active = False
            self.user.save(update_fields=["is_active"])
        elif reason == "removed":
            self.organization.members.remove(self.user)
        elif reason == "no_email":
            self.user.email = ""
            self.user.save(update_fields=["email"])
        elif reason == "deleted":
            SignalFirstReportNotification.objects.for_team(self.team.id).update(activated_by=None)
        with patch(f"{MODULE}.may_read_reports", return_value=reason != "no_access"):
            deliver_first_report_email(self.team.id)
        self.send.assert_not_called()
        assert self.notification().cancelled_at is not None

    @parameterized.expand(
        [
            ("quota", TransactionalEmailRetryableError("rate_limited")),
            ("connect", TransactionalEmailRetryableError("connect_timeout")),
            ("template", TransactionalEmailRejected("http_404")),
            ("setup", ImproperlyConfigured()),
        ]
    )
    @time_machine.travel("2026-01-15T12:01:00Z", tick=False)
    def test_confirmed_rejection_retries_the_same_report(self, _name: str, error: Exception) -> None:
        first = self.report()
        self.send.side_effect = error
        with self.assertRaises(type(error)):
            deliver_first_report_email(self.team.id)
        initial_send = self.send.call_args
        assert self.notification().send_started_at is None
        assert self.notification().last_error
        first.summary = "Updated after the first send attempt."
        first.save(update_fields=["summary"])
        SignalReportArtefact.objects.create(
            team=self.team,
            report=first,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": "P0", "explanation": "Impact increased after the first send attempt."}),
        )
        self.report(first_visible_at=timezone.now() - timedelta(seconds=1))
        self.send.side_effect = None

        deliver_first_report_email(self.team.id)

        assert self.send.call_args == initial_send
        assert initial_send.kwargs["message_data"]["report_id"] == str(first.id)
        assert self.notification().queued_at is not None

    def test_project_access_is_required_even_with_task_access(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL},
            {"key": AvailableFeature.ROLE_BASED_ACCESS, "name": AvailableFeature.ROLE_BASED_ACCESS},
        ]
        self.organization.save(update_fields=["available_product_features"])
        recipient = User.objects.create_and_join(self.organization, "recipient@example.com", None)
        SignalFirstReportNotification.objects.for_team(self.team.id).update(activated_by=recipient)
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        self.report()
        assert may_read_reports(user=recipient, team=self.team)

        deliver_first_report_email(self.team.id)

        self.send.assert_not_called()
        assert self.notification().cancelled_at is not None

    def test_retry_after_blocks_early_dispatch_and_recovery_until_due(self) -> None:
        first = self.report()
        self.post.return_value.status_code = 429
        self.post.return_value.headers = {"Retry-After": "3600"}
        self.post.return_value.json.return_value = {"code": "rate_limited"}

        with patch(f"{TASK_MODULE}.capture_exception"), self.assertRaises(Retry) as raised:
            dispatch_first_report_notification.apply(args=(self.team.id,), throw=True)

        assert raised.exception.when == 3600
        assert self.notification().next_attempt_at == timezone.now() + timedelta(hours=1)
        assert self.notification().send_started_at is None
        initial_send = self.send.call_args
        self.post.return_value.status_code = 202
        self.post.return_value.json.return_value = {"message_id": "example-message-id"}

        with time_machine.travel("2026-01-15T12:59:59Z", tick=False):
            self.report()
            dispatch_first_report_notification(self.team.id)
            with patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue:
                sweep_first_report_notifications()
            enqueue.assert_not_called()
            self.send.assert_called_once()

        with time_machine.travel("2026-01-15T13:00:00Z", tick=False):
            with patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue:
                sweep_first_report_notifications()
            enqueue.assert_called_once_with(self.team.id)
            dispatch_first_report_notification(self.team.id)

        assert self.send.call_count == 2
        assert self.send.call_args == initial_send
        assert initial_send.kwargs["message_data"]["report_id"] == str(first.id)
        assert self.notification().queued_at is not None
        assert self.notification().next_attempt_at is None

    @parameterized.expand(
        [(SignalReport.Status.CANDIDATE,), (SignalReport.Status.IN_PROGRESS,), (SignalReport.Status.PENDING_INPUT,)]
    )
    def test_selected_report_waits_for_research_before_retry(self, status: str) -> None:
        report = self.report()
        self.send.side_effect = TransactionalEmailRetryableError("rate_limited")
        with self.assertRaises(TransactionalEmailRetryableError):
            deliver_first_report_email(self.team.id)
        initial_send = self.send.call_args
        self.send.side_effect = None
        SignalReport.objects.filter(pk=report.pk).update(status=status)

        deliver_first_report_email(self.team.id)

        self.send.assert_called_once()
        assert self.notification().cancelled_at is None
        assert self.notification().send_started_at is None
        SignalReport.objects.filter(pk=report.pk).update(status=SignalReport.Status.READY)
        deliver_first_report_email(self.team.id)
        assert self.send.call_count == 2
        assert self.send.call_args == initial_send
        assert self.notification().queued_at is not None

    @parameterized.expand(
        [
            ("ambiguous_response", TransactionalEmailDeliveryUncertain("request_failed")),
            ("invalid_response", ValueError()),
        ]
    )
    def test_uncertain_send_is_not_repeated(self, _name: str, error: Exception) -> None:
        self.report()
        self.send.side_effect = error
        with self.assertRaises(type(error)):
            deliver_first_report_email(self.team.id)
        self.send.side_effect = None
        deliver_first_report_email(self.team.id)
        with patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue:
            sweep_first_report_notifications()
        enqueue.assert_not_called()
        self.send.assert_called_once()
        assert self.notification().send_started_at is not None
        assert self.notification().queued_at is None
        assert self.notification().last_error == "delivery_uncertain"

    def test_worker_loss_does_not_expire_a_send_and_duplicate_it(self) -> None:
        self.report()
        SignalFirstReportNotification.objects.for_team(self.team.id).update(
            send_started_at=timezone.now() - timedelta(days=1)
        )
        deliver_first_report_email(self.team.id)
        self.send.assert_not_called()

    def test_concurrent_dispatch_does_not_send_twice(self) -> None:
        self.report()

        def send(*_args: object, **_kwargs: object) -> str:
            deliver_first_report_email(self.team.id)
            return "example-message-id"

        self.send.side_effect = send
        deliver_first_report_email(self.team.id)
        self.send.assert_called_once()
        assert self.notification().queued_at is not None

    def test_environment_activation_and_reports_keep_their_own_recipient(self) -> None:
        child = Team.objects.create(organization=self.organization, parent_team=self.team, name="Staging")
        other_user = User.objects.create_and_join(self.organization, "staging@example.com", None)
        register_first_report_notification(team=child, user=other_user)
        report = self.report(team=child)
        deliver_first_report_email(self.team.id)
        self.send.assert_not_called()
        deliver_first_report_email(child.id)
        sent = self.send.call_args.kwargs
        assert sent["to"] == other_user.email
        assert sent["distinct_id"] == str(other_user.distinct_id)
        assert sent["message_data"]["project_id"] == child.id
        assert sent["message_data"]["report_id"] == str(report.id)
        assert self.notification().queued_at is None

    @parameterized.expand([("suppressed",), ("deleted",)])
    def test_selected_report_removed_before_retry_is_not_replaced(self, reason: str) -> None:
        report = self.report()
        self.send.side_effect = TransactionalEmailRetryableError("rate_limited")
        with self.assertRaises(TransactionalEmailRetryableError):
            deliver_first_report_email(self.team.id)
        if reason == "deleted":
            report.delete()
        else:
            SignalReport.objects.filter(pk=report.pk).update(status=SignalReport.Status.SUPPRESSED)
        self.report()
        self.send.side_effect = None
        deliver_first_report_email(self.team.id)
        self.send.assert_called_once()
        assert self.notification().cancelled_at is not None

    def test_disabled_flag_preserves_notification_until_enabled(self) -> None:
        self.report()
        self.email_flag.return_value = False

        deliver_first_report_email(self.team.id)

        self.send.assert_not_called()
        assert self.notification().send_started_at is None
        assert self.notification().cancelled_at is None
        assert self.notification().report_id is None
        self.email_flag.return_value = True
        deliver_first_report_email(self.team.id)
        self.send.assert_called_once()
        assert self.notification().queued_at is not None

    @parameterized.expand([("not_cloud",), ("no_project",), ("no_key",), ("no_host",)])
    def test_disabled_delivery_does_not_claim_a_notification(self, reason: str) -> None:
        self.report()
        with (
            patch(f"{MODULE}.is_cloud", return_value=reason != "not_cloud"),
            patch(f"{TASK_MODULE}.is_cloud", return_value=reason != "not_cloud"),
            patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue,
            override_settings(
                POSTHOG_PROJECT_ID=0 if reason == "no_project" else 123456789,
                POSTHOG_TRANSACTIONAL_EMAIL_API_KEY="" if reason == "no_key" else "phs_fake_transactional_key",
                POSTHOG_HOST="" if reason == "no_host" else "https://us.posthog.com",
            ),
        ):
            deliver_first_report_email(self.team.id)
            with self.assertNumQueries(0):
                sweep_first_report_notifications()
            enqueue.assert_not_called()
        self.send.assert_not_called()
        assert self.notification().send_started_at is None

    def test_rollback_does_not_queue_a_notification_and_transient_ready_is_not_sent(self) -> None:
        with patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError), transaction.atomic():
                    self.report()
                    raise RuntimeError("rollback")
            enqueue.assert_not_called()
            with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
                report = self.report()
                report.status = SignalReport.Status.CANDIDATE
                report.save(update_fields=["status"])
            enqueue.assert_called_once_with(self.team.id)
        deliver_first_report_email(self.team.id)
        self.send.assert_not_called()

    def test_sweep_recovers_a_missing_enqueue_without_crossing_tenants(self) -> None:
        self.report()
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other org"))
        self.report(team=other_team)
        with patch(f"{TASK_MODULE}.dispatch_first_report_notification.delay") as enqueue:
            sweep_first_report_notifications()
        enqueue.assert_called_once_with(self.team.id)
        deliver_first_report_email(other_team.id)
        self.send.assert_not_called()
        deliver_first_report_email(self.team.id)
        self.send.assert_called_once()

    @parameterized.expand([("report",), ("judgment",)])
    def test_enqueue_failure_does_not_abort_later_commit_callbacks(self, trigger: str) -> None:
        report = self.report(status=SignalReport.Status.IN_PROGRESS)
        following_callback = Mock()
        with (
            patch(
                f"{TASK_MODULE}.dispatch_first_report_notification.delay",
                side_effect=RuntimeError("broker unavailable"),
            ),
            self.assertLogs(level="ERROR"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            if trigger == "report":
                report.status = SignalReport.Status.READY
                report.save(update_fields=["status"])
            else:
                SignalReportArtefact.objects.create(
                    team=self.team,
                    report=report,
                    type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
                    content='{"actionability":"immediately_actionable","already_addressed":false}',
                )
            transaction.on_commit(following_callback)
        following_callback.assert_called_once()

    @parameterized.expand([("dispatch",), ("sweep",)])
    def test_task_captures_and_reraises_failures(self, task_name: str) -> None:
        error = RuntimeError("notification failed")
        target = "deliver_first_report_email" if task_name == "dispatch" else "dispatch_first_report_notification.delay"
        task = dispatch_first_report_notification if task_name == "dispatch" else sweep_first_report_notifications
        args = (self.team.id,) if task_name == "dispatch" else ()
        with (
            patch(f"{TASK_MODULE}.{target}", side_effect=error),
            patch(f"{TASK_MODULE}.capture_exception") as capture,
            self.assertRaises(RuntimeError) as raised,
        ):
            task(*args)
        assert raised.exception is error
        capture.assert_called_once_with(error)
