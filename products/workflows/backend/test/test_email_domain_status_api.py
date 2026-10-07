from collections.abc import Callable
from itertools import product

from unittest.mock import ANY, patch

from django.core.cache import cache

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.team import Team
from posthog.models.utils import hash_key_value

from products.workflows.backend.test.email_domain_api_test_case import (
    ALL_KINDS,
    DOMAIN,
    ROOT_DOMAIN,
    EmailDomainApiTestCase,
    record_statuses,
    step_states,
)
from products.workflows.backend.test.fakes.fake_dns import dns_operation
from products.workflows.backend.test.fakes.faults import AwsFault, DnsFault
from products.workflows.backend.test.fakes.world import EmailDomainWorld

SES_STATUS_READS = (
    "ses.get_identity_verification_attributes",
    "ses.get_identity_dkim_attributes",
    "ses.get_identity_mail_from_domain_attributes",
    "sts.get_caller_identity",
    "sesv2.list_resource_tenants",
)


class TestEmailDomainVerification(EmailDomainApiTestCase):
    def test_senders_become_verified_as_the_records_are_published_and_the_event_fires_once(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        sibling = self.create_sender(f"news@{DOMAIN}")
        self.world.ses.identities[DOMAIN].checks_paused = True

        body = self.status_body(sender)
        assert (body["status"], body["verified"], step_states(body)) == (
            "pending",
            False,
            ["done", "pending", "pending"],
        )
        assert {status for statuses in record_statuses(body).values() for status in statuses} == {"pending"}
        records = body["records"]

        for kind in ALL_KINDS[:-1]:
            self.publish(records, kind)
            body = self.status_body(sender)
            assert (body["status"], set(record_statuses(body)[kind])) == ("pending", {"found"}), kind

        self.publish(records, "dmarc")
        body = self.status_body(sender)
        assert (body["status"], step_states(body)) == ("records_found", ["done", "done", "pending"])
        assert not self.is_verified(sender)
        assert self.verified_events() == []

        self.world.ses.identities[DOMAIN].checks_paused = False
        body = self.status_body(sender)
        assert (body["status"], body["verified"], step_states(body)) == ("verified", True, ["done", "done", "done"])
        assert record_statuses(body) == {
            "verification": ["verified"],
            "dkim": ["verified"] * 3,
            "spf": ["found"],
            "mail_from_mx": ["verified"],
            "mail_from_spf": ["verified"],
            "dmarc": ["verified"],
        }
        assert self.is_verified(sender) and self.is_verified(sibling)
        assert self.verified_events() == [
            ((ANY, "email domain verified", {"method": "manual", "seconds_since_created": ANY}), {"team": ANY})
        ]
        self.reload_workers.assert_called_once_with(self.team.id, sorted([sender, sibling]))
        assert self.world.ses.writes.count("verify_domain_identity") == 2

        late_sender = self.create_sender(f"billing@{DOMAIN}")
        assert self.status_body(late_sender)["verified"] is True
        assert self.is_verified(late_sender)
        assert len(self.verified_events()) == 1

    @parameterized.expand(
        [(False, False, 404), (True, False, 200), (False, True, 200), (True, True, 200), (None, None, 404)]
    )
    def test_status_reads_ses_without_writing_to_it(
        self, wizard_enabled: bool | None, agent_enabled: bool | None, expected_status: int
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        writes_after_create = list(self.world.ses.writes)
        self.feature_flags.side_effect = lambda key, *args, **kwargs: {
            "workflows-email-domain-wizard": wizard_enabled,
            "workflows-email-domain-agent-setup": agent_enabled,
        }.get(key, False)
        response = self.get_status(sender)
        assert response.status_code == expected_status, response.json()
        if expected_status == 200:
            assert response.json()["status"] == "verified"

        assert self.world.ses.writes == writes_after_create

    def test_status_is_cached_until_refresh(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        records = self.records_to_publish(sender)
        assert self.status_body(sender, refresh=False)["status"] == "pending"

        self.publish(records, *ALL_KINDS)

        assert self.status_body(sender, refresh=False)["status"] == "pending"
        assert self.status_body(sender, refresh=True)["status"] == "verified"

    def test_verification_through_a_personal_api_key_is_reported_as_agent_setup(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        PersonalAPIKey.objects.create(
            label="Agent", user=self.user, secure_value=hash_key_value("agent_key"), scopes=["integration:read"]
        )
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer agent_key")

        assert self.status_body(sender)["verified"] is True

        assert self.verified_event_methods() == ["agent"]

    def test_failed_worker_reload_keeps_the_verified_answer_and_is_not_retried(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        self.reload_workers.side_effect = ConnectionError("Redis is down")

        with patch("posthog.models.integration.email.capture_exception") as capture_exception:
            assert self.status_body(sender)["verified"] is True
        capture_exception.assert_called_once()

        self.reload_workers.side_effect = None
        assert self.status_body(sender)["verified"] is True
        assert self.is_verified(sender)
        assert self.reload_workers.call_count == 1
        assert len(self.verified_events()) == 1


class TestEmailDomainPartialSesState(EmailDomainApiTestCase):
    @parameterized.expand(
        [
            (
                "verification_token_missing",
                lambda world: setattr(world.ses.identities[DOMAIN], "verification_token", None),
                "not_started",
                {},
            ),
            (
                "dkim_never_enabled",
                lambda world: setattr(world.ses.identities[DOMAIN], "dkim_tokens", ()),
                "records_found",
                {
                    "verification": ["verified"],
                    "spf": ["found"],
                    "mail_from_mx": ["verified"],
                    "mail_from_spf": ["verified"],
                    "dmarc": ["verified"],
                },
            ),
            (
                "only_two_of_three_dkim_records_published",
                lambda world: world.dns.unpublish(
                    f"{world.ses.identities[DOMAIN].dkim_tokens[2]}._domainkey.{DOMAIN}", "CNAME"
                ),
                "pending",
                {"dkim": ["found", "found", "pending"]},
            ),
            (
                "mail_from_never_set",
                lambda world: setattr(world.ses.identities[DOMAIN], "mail_from_domain", None),
                "records_found",
                {"mail_from_mx": ["found"], "mail_from_spf": ["found"]},
            ),
            (
                "mail_from_set_for_another_senders_subdomain",
                lambda world: setattr(world.ses.identities[DOMAIN], "mail_from_domain", f"bounce.{DOMAIN}"),
                "records_found",
                {"mail_from_mx": ["found"], "mail_from_spf": ["found"]},
            ),
            (
                "mail_from_mx_published_without_its_spf_record",
                lambda world: world.dns.unpublish(f"feedback.{DOMAIN}", "TXT"),
                "verified",
                {"mail_from_mx": ["verified"], "mail_from_spf": ["pending"]},
            ),
            (
                "second_mx_record_on_the_bounce_subdomain",
                lambda world: world.dns.publish(f"feedback.{DOMAIN}", "MX", "20 mx.example.net."),
                "records_found",
                {"mail_from_mx": ["found"], "mail_from_spf": ["found"]},
            ),
            (
                "identity_owned_by_another_teams_tenant",
                lambda world: world.ses.transfer_identity(DOMAIN, "team-999999"),
                "records_found",
                {"verification": ["verified"], "dkim": ["verified"] * 3},
            ),
            (
                "dkim_failed",
                lambda world: setattr(world.ses.identities[DOMAIN], "forced_dkim_status", "Failed"),
                "failed",
                {"dkim": ["found"] * 3},
            ),
            (
                "verification_temporary_failure",
                lambda world: setattr(world.ses.identities[DOMAIN], "forced_verification_status", "TemporaryFailure"),
                "temporary_failure",
                {"verification": ["found"]},
            ),
        ]
    )
    def test_reports_partial_ses_state_without_verifying(
        self,
        _name: str,
        arrange: Callable[[EmailDomainWorld], object],
        expected_status: str,
        expected_records: dict[str, list[str]],
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        arrange(self.world)

        body = self.status_body(sender)

        assert body["status"] == expected_status
        assert {kind: statuses for kind, statuses in record_statuses(body).items() if kind in expected_records} == (
            expected_records
        )
        if expected_status != "verified":
            assert (body["verified"], self.is_verified(sender), self.verified_events()) == (False, False, [])


class TestEmailDomainTenantScoping(EmailDomainApiTestCase):
    def test_verifying_a_domain_leaves_other_teams_senders_on_it_untouched(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        sender = self.create_sender(f"hello@{DOMAIN}")
        other_teams_sender = self.create_sender(f"hello@{DOMAIN}", team=other_team)
        self.publish(self.records_to_publish(sender), *ALL_KINDS)

        assert self.status_body(sender)["verified"] is True

        assert self.is_verified(sender)
        assert not self.is_verified(other_teams_sender)
        self.reload_workers.assert_called_once_with(self.team.id, [sender])

    def test_a_sender_of_another_organization_is_not_found(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Other")
        foreign_sender = Integration.objects.create(
            team=other_team,
            kind="email",
            integration_id=f"hello@{DOMAIN}",
            config={"email": f"hello@{DOMAIN}", "domain": DOMAIN, "provider": "ses", "verified": False},
        )

        response = self.get_status(foreign_sender.id)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not self.is_verified(foreign_sender.id)


class TestEmailDomainDnsLookups(EmailDomainApiTestCase):
    def test_dmarc_record_hosted_in_another_zone_through_a_cname_counts(self) -> None:
        self.world.dns.add_zone("dmarc-reports.example.net")
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS[:-1])
        self.world.dns.publish(f"_dmarc.{DOMAIN}", "CNAME", f"{DOMAIN}._dmarc.dmarc-reports.example.net.")
        self.world.dns.publish_txt(f"{DOMAIN}._dmarc.dmarc-reports.example.net", "v=DMARC1; p=reject")

        body = self.status_body(sender)

        assert (body["status"], record_statuses(body)["dmarc"]) == ("verified", ["verified"])

    @parameterized.expand([(DnsFault.TIMEOUT,), (DnsFault.SERVFAIL,)])
    def test_public_resolver_confirms_a_record_the_zone_nameservers_cannot_answer(self, fault: DnsFault) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        self.world.faults.inject(dns_operation(f"_dmarc.{DOMAIN}", "TXT", at="zone"), fault)

        assert self.status_body(sender)["status"] == "verified"

    def test_zone_nameservers_confirm_a_record_the_public_resolver_has_not_seen_yet(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        self.world.faults.inject(dns_operation(f"_dmarc.{DOMAIN}", "TXT", at="public"), DnsFault.NXDOMAIN)

        assert self.status_body(sender)["status"] == "verified"

    @parameterized.expand(
        [
            ("zone_apex_lookup", ROOT_DOMAIN, "SOA"),
            ("nameserver_lookup", ROOT_DOMAIN, "NS"),
            ("nameserver_address_lookup", "ns1.example-dns.net", "A"),
        ]
    )
    def test_failing_zone_nameserver_discovery_falls_back_to_the_public_resolver(
        self, _name: str, name: str, rdtype: str
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)
        self.world.faults.inject(dns_operation(name, rdtype), DnsFault.SERVFAIL)

        assert self.status_body(sender)["status"] == "verified"

    def test_txt_records_split_into_several_strings_count(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        records = self.records_to_publish(sender)
        self.publish(records, "verification", "dkim", "mail_from_mx")
        self.world.dns.publish(DOMAIN, "TXT", '"v=spf1 include:" "amazonses.com ~all"')
        self.world.dns.publish(f"feedback.{DOMAIN}", "TXT", '"v=spf1 " "include:amazonses.com ~all"')
        self.world.dns.publish(f"_dmarc.{DOMAIN}", "TXT", '"v=DMARC1; " "p=none;"')

        body = self.status_body(sender)

        assert body["status"] == "verified"
        assert record_statuses(body)["spf"] == ["found"]

    def test_never_queries_a_zone_nameserver_at_an_internal_address(self) -> None:
        self.world.dns.add_zone("internal.example.org", nameservers={"ns.internal.example.org": "10.0.0.53"})
        sender = self.create_sender("hello@internal.example.org")
        self.publish(self.records_to_publish(sender, domain="internal.example.org"), *ALL_KINDS)

        assert self.status_body(sender)["status"] == "verified"
        assert "10.0.0.53" not in self.world.dns.queried_addresses


class TestEmailDomainStatusChaos(EmailDomainApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.capture_exception = self.enterContext(patch("products.workflows.backend.providers.ses.capture_exception"))
        self.sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(self.sender), *ALL_KINDS)
        cache.clear()

    @parameterized.expand(
        product(SES_STATUS_READS, list(AwsFault)), name_func=lambda f, _n, p: f"{f.__name__}_{p.args[0]}_{p.args[1]}"
    )
    def test_aws_failure_answers_503_and_the_next_poll_recovers(self, operation: str, fault: AwsFault) -> None:
        self.world.faults.inject(operation, fault)

        response = self.get_status(self.sender, refresh=False)

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {
            "type": "server_error",
            "code": "email_provider_unavailable",
            "detail": "Couldn't reach the email provider to check this domain. Try again in a moment.",
            "attr": None,
        }
        assert (self.is_verified(self.sender), self.verified_events()) == (False, [])
        assert self.capture_exception.called is (fault != AwsFault.THROTTLING)

        self.world.faults.clear()
        assert self.status_body(self.sender, refresh=False)["verified"] is True
        assert self.verified_event_methods() == ["manual"]

    @parameterized.expand(
        product(
            [
                ("verification", f"_amazonses.{DOMAIN}", "TXT", "verified"),
                ("dkim", None, "CNAME", "verified"),
                ("spf", DOMAIN, "TXT", "found"),
                ("mail_from_mx", f"feedback.{DOMAIN}", "MX", "verified"),
                ("mail_from_spf", f"feedback.{DOMAIN}", "TXT", "verified"),
                ("dmarc", f"_dmarc.{DOMAIN}", "TXT", "verified"),
            ],
            [DnsFault.TIMEOUT, DnsFault.SERVFAIL],
        ),
        name_func=lambda f, _n, p: f"{f.__name__}_{p.args[0][0]}_{p.args[1]}",
    )
    def test_unanswered_dns_lookup_holds_verification_until_it_answers(
        self, lookup: tuple[str, str | None, str, str], fault: DnsFault
    ) -> None:
        kind, hostname, rdtype, status_once_answered = lookup
        dkim_token = self.world.ses.identities[DOMAIN].dkim_tokens[0]
        self.world.faults.inject(dns_operation(hostname or f"{dkim_token}._domainkey.{DOMAIN}", rdtype), fault)

        body = self.status_body(self.sender, refresh=False)

        assert body["status"] in ("pending", "records_found")
        assert (body["verified"], self.is_verified(self.sender), self.verified_events()) == (False, False, [])

        self.world.faults.clear()
        body = self.status_body(self.sender, refresh=False)
        assert (body["status"], record_statuses(body)[kind][0]) == ("verified", status_once_answered)
        assert self.verified_event_methods() == ["manual"]
