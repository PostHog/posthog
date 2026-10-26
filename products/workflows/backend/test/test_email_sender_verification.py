from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import OperationalError
from django.utils import timezone

import dns.resolver
from botocore.exceptions import ClientError, EndpointConnectionError
from parameterized import param, parameterized
from prometheus_client import REGISTRY
from redis.exceptions import RedisError
from structlog.testing import capture_logs

from posthog.models.integration import EmailIntegration, Integration
from posthog.redis import get_client

from products.workflows.backend.facade.tasks import refresh_new_email_senders, refresh_settled_email_senders
from products.workflows.backend.facade.writes import disable
from products.workflows.backend.models import HogFlow
from products.workflows.backend.services.email_sender_verification import EmailSenderVerification
from products.workflows.backend.tasks.waiting_workflows import enable_waiting_workflows_task


class TestEmailSenderVerification(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        redis = get_client()
        for key in redis.scan_iter("workflows:email_sender_verification:*"):
            redis.delete(key)
        self.ses_clock = {"now": 0.0}
        for name, fake in [
            ("monotonic", lambda: self.ses_clock["now"]),
            ("sleep", lambda seconds: self.ses_clock.update(now=self.ses_clock["now"] + seconds)),
        ]:
            clock_patch = patch(f"products.workflows.backend.providers.ses.{name}", side_effect=fake)
            clock_patch.start()
            self.addCleanup(clock_patch.stop)

    def _create_sender(self, domain: str, local_part: str = "sender", **config: Any) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id=f"{local_part}@{domain}",
            config={
                "email": f"{local_part}@{domain}",
                "domain": domain,
                "name": "Example sender",
                "provider": "ses",
                "mail_from_subdomain": "feedback",
                "verified": False,
                **config,
            },
        )

    def _mock_ses(
        self,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        *,
        dkim_status: str = "Success",
        has_dmarc: bool = True,
        has_tenant: bool = True,
        mail_from_domain: str | None = None,
    ) -> MagicMock:
        ses = mock_boto_client.return_value
        ses.get_identity_verification_attributes.side_effect = lambda Identities: {
            "VerificationAttributes": {domain: {"VerificationStatus": "Success"} for domain in Identities}
        }
        ses.get_identity_dkim_attributes.side_effect = lambda Identities: {
            "DkimAttributes": {domain: {"DkimVerificationStatus": dkim_status} for domain in Identities}
        }
        ses.get_identity_mail_from_domain_attributes.side_effect = lambda Identities: {
            "MailFromDomainAttributes": {
                domain: {"MailFromDomainStatus": "Success", "MailFromDomain": mail_from_domain or f"feedback.{domain}"}
                for domain in Identities
            }
        }
        ses.get_caller_identity.return_value = {"Account": "123456789012"}
        ses.list_resource_tenants.return_value = {
            "ResourceTenants": [{"TenantName": f"team-{self.team.id}"}] if has_tenant else []
        }
        mock_resolver.return_value.resolve.return_value = [SimpleNamespace(strings=[b"v=DMARC1; p=none;"])]
        if not has_dmarc:
            mock_resolver.return_value.resolve.side_effect = dns.resolver.NXDOMAIN()
        ses.verify_domain_identity.side_effect = RuntimeError("Background checks must not create SES identities")
        ses.verify_domain_dkim.side_effect = RuntimeError("Background checks must not change DKIM")
        ses.set_identity_mail_from_domain.side_effect = RuntimeError("Background checks must not change MAIL FROM")
        return ses

    def _timestamp(self, age: timedelta) -> int:
        return int((timezone.now() - age).timestamp())

    def _verified(self, *senders: Integration) -> list[bool]:
        return [
            self.client.get(f"/api/projects/{self.team.id}/integrations/{sender.id}/").json()["config"]["verified"]
            for sender in senders
        ]

    def _default_sender_id(self) -> int | None:
        return self.client.get(f"/api/environments/{self.team.id}/").json()["workflows_config"][
            "default_email_integration_id"
        ]

    @parameterized.expand(
        [
            param("verified", expected_verified=True),
            param("dkim_pending", dkim_status="Pending"),
            param("dmarc_missing", has_dmarc=False),
            param("tenant_missing", has_tenant=False),
            param("mail_from_changed", mail_from_domain="other.example.com"),
            param("mail_from_differs_in_case", mail_from_domain="Feedback.Example.com.", expected_verified=True),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_background_verification_updates_sender_status_without_ui(
        self,
        _name: str,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        dkim_status: str = "Success",
        has_dmarc: bool = True,
        has_tenant: bool = True,
        mail_from_domain: str | None = None,
        expected_verified: bool = False,
    ) -> None:
        sender = self._create_sender("example.com")
        ses = self._mock_ses(
            mock_boto_client,
            mock_resolver,
            dkim_status=dkim_status,
            has_dmarc=has_dmarc,
            has_tenant=has_tenant,
            mail_from_domain=mail_from_domain,
        )

        refresh_new_email_senders()

        assert self._verified(sender) == [expected_verified]
        assert self._default_sender_id() == (sender.id if expected_verified else None)
        assert [call.kwargs["Identities"] for call in ses.get_identity_verification_attributes.call_args_list] == [
            ["example.com"]
        ]

        if expected_verified:
            mock_boto_client.reset_mock()
            refresh_new_email_senders()
            mock_boto_client.assert_not_called()

    @parameterized.expand(
        [
            param("new_sender_every_minute", age=timedelta(minutes=10), sweep=refresh_new_email_senders, checked=True),
            param(
                "new_sender_not_in_five_minute_sweep", age=timedelta(minutes=10), sweep=refresh_settled_email_senders
            ),
            param(
                "settled_sender_every_five_minutes",
                age=timedelta(hours=2),
                sweep=refresh_settled_email_senders,
                checked=True,
            ),
            param("settled_sender_not_in_minute_sweep", age=timedelta(hours=2), sweep=refresh_new_email_senders),
            param("stale_sender", age=timedelta(days=8), sweep=refresh_settled_email_senders),
            param(
                "old_sender_with_recent_request_every_minute",
                age=timedelta(days=30),
                requested_age=timedelta(minutes=10),
                sweep=refresh_new_email_senders,
                checked=True,
            ),
            param(
                "new_sender_with_stale_request",
                age=timedelta(minutes=10),
                requested_age=timedelta(days=8),
                sweep=refresh_new_email_senders,
            ),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_sweeps_check_senders_by_age(
        self,
        _name: str,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        age: timedelta,
        sweep: Callable[[], None],
        requested_age: timedelta | None = None,
        checked: bool = False,
    ) -> None:
        requested_at: dict[str, Any] = (
            {} if requested_age is None else {"verification_requested_at": self._timestamp(requested_age)}
        )
        sender = self._create_sender("example.com", **requested_at)
        Integration.objects.filter(id=sender.id).update(created_at=timezone.now() - age)
        ses = self._mock_ses(mock_boto_client, mock_resolver)

        sweep()

        assert ses.get_identity_verification_attributes.called is checked
        assert self._verified(sender) == [checked]

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_advisor_event_makes_pending_senders_on_its_domain_due_on_the_next_minute_sweep(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        sender, other = (self._create_sender(domain) for domain in ["example.com", "other.example.com"])
        Integration.objects.filter(id__in=[sender.id, other.id]).update(created_at=timezone.now() - timedelta(days=30))
        ses = self._mock_ses(mock_boto_client, mock_resolver)

        EmailSenderVerification.request_domain_check("Example.com")
        refresh_new_email_senders()

        assert self._verified(sender, other) == [True, False]
        assert [call.kwargs["Identities"] for call in ses.get_identity_verification_attributes.call_args_list] == [
            ["example.com"]
        ]

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_advisor_requested_sender_whose_check_fails_is_retried_on_the_next_sweep(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        sender = self._create_sender("example.com")
        Integration.objects.filter(id=sender.id).update(created_at=timezone.now() - timedelta(days=30))
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        ses.list_resource_tenants.side_effect = [
            ClientError({"Error": {"Code": "Throttling", "Message": "Rate exceeded"}}, "ListResourceTenants"),
            {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]},
        ]
        EmailSenderVerification.request_domain_check("example.com")

        refresh_new_email_senders()
        assert self._verified(sender) == [False]

        refresh_new_email_senders()
        assert self._verified(sender) == [True]

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_tenant_reads_for_ready_senders_are_spaced_apart(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        senders = [self._create_sender(domain) for domain in ["first.example.com", "second.example.com"]]
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        tenant_read_times: list[float] = []

        def read_tenants(ResourceArn: str) -> dict[str, list[dict[str, str]]]:
            tenant_read_times.append(self.ses_clock["now"])
            return {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}

        ses.list_resource_tenants.side_effect = read_tenants

        refresh_new_email_senders()

        assert self._verified(*senders) == [True, True]
        assert tenant_read_times == [0.0, 2.0]

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_sender_edited_during_check_still_verifies_siblings_on_the_checked_subdomain(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        sender = self._create_sender("example.com")
        sibling = self._create_sender("example.com", local_part="sibling")
        ses = self._mock_ses(mock_boto_client, mock_resolver)

        def edit_sender(**kwargs: str) -> dict[str, list[dict[str, str]]]:
            Integration.objects.filter(id=sender.id).update(config={**sender.config, "mail_from_subdomain": "updated"})
            return {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}

        ses.list_resource_tenants.side_effect = edit_sender

        refresh_new_email_senders()

        assert self._verified(sender, sibling) == [False, True]
        assert self._default_sender_id() is None

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_overlapping_sweep_returns_without_checking(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        sender = self._create_sender("example.com")
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        read_statuses = ses.get_identity_verification_attributes.side_effect

        def overlap_sweep(Identities: list[str]) -> dict[str, dict[str, dict[str, str]]]:
            ses.get_identity_verification_attributes.side_effect = read_statuses
            refresh_new_email_senders()
            return read_statuses(Identities=Identities)

        ses.get_identity_verification_attributes.side_effect = overlap_sweep

        refresh_new_email_senders()

        assert ses.get_identity_verification_attributes.call_count == 1
        assert self._verified(sender) == [True]

    @parameterized.expand(
        [
            param("provider_failure", fail_first=True, first_sweep=[False, True], second_sweep=[True, True]),
            param("budget_exhausted", slow_checks=True, first_sweep=[True, False], second_sweep=[True, True]),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_interrupted_sweep_does_not_block_other_senders_and_recovers_on_next_sweep(
        self,
        _name: str,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        first_sweep: list[bool],
        second_sweep: list[bool],
        fail_first: bool = False,
        slow_checks: bool = False,
    ) -> None:
        senders = [self._create_sender(domain) for domain in ["first.example.com", "second.example.com"]]
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        clock = {"now": 0.0}

        def check_tenants(ResourceArn: str) -> dict[str, list[dict[str, str]]]:
            if slow_checks:
                clock["now"] += 200
            if fail_first and ResourceArn.endswith("/first.example.com"):
                raise EndpointConnectionError(endpoint_url="https://ses.example.com")
            return {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}

        ses.list_resource_tenants.side_effect = check_tenants

        with patch(
            "products.workflows.backend.services.email_sender_verification.monotonic", side_effect=lambda: clock["now"]
        ):
            refresh_new_email_senders()
            assert self._verified(*senders) == first_sweep
            assert [call.kwargs["Identities"] for call in ses.get_identity_verification_attributes.call_args_list] == [
                ["first.example.com", "second.example.com"]
            ]

            fail_first = False
            arrival = self._create_sender("new.example.com")
            ses.get_identity_verification_attributes.reset_mock()
            refresh_new_email_senders()
            assert self._verified(*senders, arrival) == [*second_sweep, not slow_checks]

            refresh_new_email_senders()
            assert self._verified(*senders, arrival) == [True, True, True]


class TestVerifiedSenderTakesWaitingWorkflowsLive(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        capture_patcher = patch("products.workflows.backend.tasks.waiting_workflows.ph_scoped_capture")
        self.mock_scoped_capture = capture_patcher.start()
        self.addCleanup(capture_patcher.stop)
        self.captured = self.mock_scoped_capture.return_value.__enter__.return_value

    def _sender(self, domain: str, *, verified: bool = False) -> Integration:
        return Integration.objects.create(
            team=self.team,
            kind="email",
            integration_id=f"hello@{domain}",
            config={"email": f"hello@{domain}", "domain": domain, "provider": "maildev", "verified": verified},
        )

    def _waiting_flow(self, *senders: Integration) -> str:
        email_steps = [
            {
                "id": f"email_{sender.id}",
                "name": "Email",
                "type": "function_email",
                "config": {"inputs": {"email": {"value": {"from": {"integrationId": sender.id}}}}},
            }
            for sender in senders
        ]
        flow = HogFlow.objects.create(
            team=self.team,
            name="Welcome",
            status="waiting_for_domain",
            actions=[
                {"id": "trigger_node", "name": "Trigger", "type": "trigger", "config": {"type": "event"}},
                *email_steps,
            ],
            enable_requested_at=timezone.now(),
            enable_requested_by=self.user,
        )
        return str(flow.id)

    def _workflow(self, flow_id: str) -> dict:
        return self.client.get(f"/api/projects/{self.team.id}/hog_flows/{flow_id}").json()

    def _verify(self, sender: Integration) -> list[Callable[[], None]]:
        with self.captureOnCommitCallbacks() as callbacks:
            EmailIntegration(sender).apply_verification({"status": "success", "dnsRecords": []})
        return callbacks

    def _captured_events(self) -> list[tuple[str, str, dict]]:
        return [
            (call.kwargs["event"], call.kwargs["distinct_id"], call.kwargs["properties"])
            for call in self.captured.call_args_list
        ]

    @parameterized.expand(
        [
            param("only_sender_flag_on", flag_on=True, expected_status="active"),
            param("only_sender_flag_off", flag_on=False, expected_status="active"),
            param("second_sender_unverified", second_sender=True, expected_status="waiting_for_domain"),
            param("turned_off_before_the_task", turned_off=True, expected_status="draft"),
        ]
    )
    def test_verifying_a_sender_takes_its_waiting_workflows_live(
        self,
        _name: str,
        expected_status: str,
        flag_on: bool = True,
        second_sender: bool = False,
        turned_off: bool = False,
    ) -> None:
        sender = self._sender("example.com")
        other_senders = [self._sender("other.example.com")] if second_sender else []
        enabled_at = timezone.now()
        with time_machine.travel(enabled_at, tick=False):
            flow_id = self._waiting_flow(sender, *other_senders)
        if turned_off:
            disable(team_id=self.team.id, hog_flow_id=UUID(flow_id))

        with (
            time_machine.travel(enabled_at + timedelta(minutes=10), tick=False),
            patch(
                "posthoganalytics.feature_enabled",
                side_effect=lambda key, *args, **kwargs: flag_on and key == "workflows-email-domain-wizard",
            ),
        ):
            callbacks = self._verify(sender)
            for _ in range(2):
                for callback in callbacks:
                    callback()

        workflow = self._workflow(flow_id)
        assert workflow["status"] == expected_status
        events = self._captured_events()
        if expected_status != "active":
            assert workflow["went_live_at"] is None
            assert events == []
            return
        assert datetime.fromisoformat(workflow["went_live_at"]) == enabled_at + timedelta(minutes=10)
        assert len(events) == 1
        name, distinct_id, properties = events[0]
        assert name == "hog_flow_activated"
        assert distinct_id == self.user.distinct_id
        assert properties["workflow_id"] == flow_id
        assert properties["activated_by"] == "domain_verified"
        assert properties["seconds_waiting"] == 600
        assert datetime.fromisoformat(properties["enable_requested_at"]) == enabled_at
        assert "source" not in properties

    def test_a_go_live_that_cannot_be_queued_keeps_the_verification(self) -> None:
        sender = self._sender("example.com")
        flow_id = self._waiting_flow(sender)
        failures_before = REGISTRY.get_sample_value("workflows_enable_waiting_failed_total") or 0

        with (
            patch.object(enable_waiting_workflows_task, "delay", side_effect=OSError("broker unreachable")),
            capture_logs() as logs,
        ):
            for callback in self._verify(sender):
                callback()

        sender.refresh_from_db()
        assert sender.config["verified"] is True
        assert [log["event"] for log in logs if log["log_level"] == "error"] == ["workflows.enable_waiting.failed"]
        assert REGISTRY.get_sample_value("workflows_enable_waiting_failed_total") == failures_before + 1
        assert self._workflow(flow_id)["status"] == "waiting_for_domain"

    @parameterized.expand([("database", OperationalError("connection lost")), ("redis", RedisError("publish failed"))])
    def test_task_logs_and_counts_a_go_live_that_fails_after_its_last_retry(self, _name, error: Exception) -> None:
        sender = self._sender("example.com", verified=True)
        flow_id = self._waiting_flow(sender)
        failures_before = REGISTRY.get_sample_value("workflows_enable_waiting_failed_total") or 0

        with (
            patch("products.workflows.backend.services.hog_flow_writes.enable_waiting", side_effect=error),
            capture_logs() as logs,
        ):
            enable_waiting_workflows_task.apply(kwargs={"team_id": self.team.id, "sender_ids": [sender.id]}, retries=5)

        assert [log["event"] for log in logs if log["log_level"] == "error"] == ["workflows.enable_waiting.failed"]
        assert REGISTRY.get_sample_value("workflows_enable_waiting_failed_total") == failures_before + 1
        assert self._workflow(flow_id)["status"] == "waiting_for_domain"
