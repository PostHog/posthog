from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from typing import Any

from posthog.test.base import APIBaseTest, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import close_old_connections, connection
from django.utils import timezone

import dns.resolver
from botocore.exceptions import ClientError, EndpointConnectionError
from parameterized import param, parameterized

from posthog.models.integration import Integration
from posthog.models.integration.email import EmailIntegration
from posthog.redis import get_client

from products.workflows.backend.facade import api as workflows_api
from products.workflows.backend.facade.tasks import refresh_new_email_senders, refresh_settled_email_senders
from products.workflows.backend.providers.ses import AWS_ACCOUNT_ID_CACHE_KEY, IDENTITY_ATTRIBUTES_BATCH_SIZE
from products.workflows.backend.services.email_sender_verification import EmailSenderVerification


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

    @parameterized.expand(
        [
            param("warm_account_lookup", account_lookup_seconds=None, expected_read_times=[0.0, 4.0]),
            param("slow_cold_account_lookup", account_lookup_seconds=3.0, expected_read_times=[3.0, 7.0]),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_tenant_reads_for_ready_senders_are_spaced_apart(
        self,
        _name: str,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        account_lookup_seconds: float | None,
        expected_read_times: list[float],
    ) -> None:
        senders = [self._create_sender(domain) for domain in ["first.example.com", "second.example.com"]]
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        if account_lookup_seconds is None:
            cache.set(AWS_ACCOUNT_ID_CACHE_KEY, "123456789012")
        else:
            cache.delete(AWS_ACCOUNT_ID_CACHE_KEY)

            def slow_account_lookup() -> dict[str, str]:
                self.ses_clock["now"] += account_lookup_seconds
                return {"Account": "123456789012"}

            ses.get_caller_identity.side_effect = slow_account_lookup
        tenant_read_times: list[float] = []

        def read_tenants(ResourceArn: str) -> dict[str, list[dict[str, str]]]:
            tenant_read_times.append(self.ses_clock["now"])
            return {"ResourceTenants": [{"TenantName": f"team-{self.team.id}"}]}

        ses.list_resource_tenants.side_effect = read_tenants

        refresh_new_email_senders()

        assert self._verified(*senders) == [True, True]
        assert tenant_read_times == expected_read_times

    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_each_status_read_is_spaced_apart_across_batches(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        for n in range(IDENTITY_ATTRIBUTES_BATCH_SIZE + 1):
            self._create_sender(f"d{n}.example.com")
        ses = self._mock_ses(mock_boto_client, mock_resolver, dkim_status="Pending")
        read_times: dict[str, list[float]] = {"verification": [], "dkim": [], "mail_from": []}

        def timed(name: str, read: Callable[..., Any], duration: float = 0.0) -> Callable[..., Any]:
            def timed_read(Identities: list[str]) -> Any:
                read_times[name].append(self.ses_clock["now"])
                if len(read_times[name]) == 1:
                    self.ses_clock["now"] += duration
                return read(Identities=Identities)

            return timed_read

        ses.get_identity_verification_attributes.side_effect = timed(
            "verification", ses.get_identity_verification_attributes.side_effect, duration=3.0
        )
        ses.get_identity_dkim_attributes.side_effect = timed("dkim", ses.get_identity_dkim_attributes.side_effect)
        ses.get_identity_mail_from_domain_attributes.side_effect = timed(
            "mail_from", ses.get_identity_mail_from_domain_attributes.side_effect
        )

        refresh_new_email_senders()

        assert read_times == {"verification": [0.0, 4.0], "dkim": [3.0, 7.0], "mail_from": [3.0, 7.0]}

    @parameterized.expand(
        [
            param(
                "leaves_time_for_the_sender_check",
                status_read_seconds=EmailSenderVerification.STATUS_READ_WORST_CASE_SECONDS - 1,
                first_sweep=[True],
            ),
            param(
                "leaves_less_than_a_sender_check_with_a_cold_account_lookup",
                status_read_seconds=EmailSenderVerification.STATUS_READ_WORST_CASE_SECONDS + 9,
                first_sweep=[False],
            ),
        ]
    )
    @patch("products.workflows.backend.providers.ses.dns.resolver.Resolver")
    @patch("products.workflows.backend.providers.ses.boto3.client")
    def test_slow_status_read_verifies_the_sender_only_when_its_check_fits_the_budget(
        self,
        _name: str,
        mock_boto_client: MagicMock,
        mock_resolver: MagicMock,
        status_read_seconds: int,
        first_sweep: list[bool],
    ) -> None:
        sender = self._create_sender("example.com")
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        clock = {"now": 0.0}
        read_statuses = ses.get_identity_verification_attributes.side_effect

        def slow_first_read(Identities: list[str]) -> Any:
            if ses.get_identity_verification_attributes.call_count == 1:
                clock["now"] += status_read_seconds
            return read_statuses(Identities=Identities)

        ses.get_identity_verification_attributes.side_effect = slow_first_read

        with patch(
            "products.workflows.backend.services.email_sender_verification.monotonic", side_effect=lambda: clock["now"]
        ):
            refresh_new_email_senders()
            assert self._verified(sender) == first_sweep

            refresh_new_email_senders()
            assert self._verified(sender) == [True]

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
    def test_a_pending_sender_does_not_hide_another_domain_with_the_same_mail_from_host(
        self, mock_boto_client: MagicMock, mock_resolver: MagicMock
    ) -> None:
        pending = self._create_sender("a.example.com")
        ready = self._create_sender("example.com", mail_from_subdomain="feedback.a")
        ses = self._mock_ses(mock_boto_client, mock_resolver)
        ses.get_identity_mail_from_domain_attributes.side_effect = lambda Identities: {
            "MailFromDomainAttributes": {
                domain: {"MailFromDomainStatus": "Success", "MailFromDomain": "feedback.a.example.com"}
                for domain in Identities
            }
        }
        dmarc = SimpleNamespace(strings=[b"v=DMARC1; p=none;"])

        def resolve(name: str, _record_type: str) -> list[SimpleNamespace]:
            if name == "_dmarc.a.example.com":
                raise dns.resolver.NXDOMAIN()
            return [dmarc]

        mock_resolver.return_value.resolve.side_effect = resolve

        refresh_new_email_senders()

        assert self._verified(pending, ready) == [False, True]

    @patch("posthog.models.integration.email.reload_integrations_on_workers")
    @patch(
        "products.workflows.backend.facade.api.verify_ses_email_domain",
        return_value={"status": "success", "dnsRecords": []},
    )
    def test_a_domain_counts_as_verified_once_across_mail_from_subdomains(
        self, _verify: MagicMock, _reload: MagicMock
    ) -> None:
        self._create_sender("example.com", verified=True)
        other_subdomain = self._create_sender("example.com", local_part="other", mail_from_subdomain="bounce")
        on_domain_verified = MagicMock()

        EmailIntegration(other_subdomain).verify(on_domain_verified=on_domain_verified)

        assert self._verified(other_subdomain) == [True]
        on_domain_verified.assert_not_called()

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


class TestDomainVerificationConcurrency(NonAtomicBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    @patch("posthog.models.integration.email.reload_integrations_on_workers")
    @patch(
        "products.workflows.backend.facade.api.verify_ses_email_domain",
        return_value={"status": "success", "dnsRecords": []},
    )
    def test_two_mail_from_groups_verifying_at_once_report_the_domain_once(
        self, _verify: MagicMock, _reload: MagicMock
    ) -> None:
        senders = [
            Integration.objects.create(
                team=self.team,
                kind="email",
                integration_id=f"{subdomain}@example.com",
                config={
                    "email": f"{subdomain}@example.com",
                    "domain": "example.com",
                    "provider": "ses",
                    "mail_from_subdomain": subdomain,
                    "verified": False,
                },
            )
            for subdomain in ["feedback", "bounce"]
        ]
        on_domain_verified = MagicMock()
        first_inside_transaction = Event()
        release_first = Event()

        set_default = workflows_api.set_default_email_sender_if_unset

        def pause_first_verification(team_id: int, integration_id: int) -> None:
            if integration_id == senders[0].id:
                first_inside_transaction.set()
                release_first.wait(timeout=10)
            set_default(team_id, integration_id)

        backend_pids: dict[int, int] = {}

        def verify(sender: Integration) -> None:
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '10s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pids[sender.id] = cursor.fetchone()[0]
                EmailIntegration(Integration.objects.get(id=sender.id)).verify(on_domain_verified=on_domain_verified)
            finally:
                close_old_connections()

        with (
            patch.object(workflows_api, "set_default_email_sender_if_unset", side_effect=pause_first_verification),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            first = executor.submit(verify, senders[0])
            assert first_inside_transaction.wait(timeout=10)
            second = executor.submit(verify, senders[1])
            deadline = monotonic() + 10
            while not (second.done() or self._waits_for_a_lock(backend_pids.get(senders[1].id))):
                assert monotonic() < deadline, "the second verification neither finished nor waited for a lock"
                sleep(0.05)
            release_first.set()
            first.result(timeout=10)
            second.result(timeout=10)

        assert [Integration.objects.get(id=sender.id).config["verified"] for sender in senders] == [True, True]
        assert on_domain_verified.call_count == 1

    def _waits_for_a_lock(self, backend_pid: int | None) -> bool:
        if backend_pid is None:
            return False
        with connection.cursor() as cursor:
            cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [backend_pid])
            row = cursor.fetchone()
        return row is not None and row[0] == "Lock"
