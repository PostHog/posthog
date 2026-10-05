from collections.abc import Callable
from typing import Any

from posthog.test.base import APIBaseTest

from django.core.cache import cache
from django.test import override_settings

from dns.rdtypes.ANY.TXT import TXT
from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import EmailIntegration, Integration

from products.workflows.backend.test.email_domain_api_test_case import (
    ALL_KINDS,
    DOMAIN,
    ROOT_DOMAIN,
    EmailDomainApiTestCase,
)
from products.workflows.backend.test.fakes.fake_dns import dns_operation
from products.workflows.backend.test.fakes.fake_domain_connect import SETTINGS_OPERATION
from products.workflows.backend.test.fakes.faults import DnsFault, HttpFault
from products.workflows.backend.test.fakes.world import EmailDomainWorld, domain_connect_signing_key_pem

CLOUDFLARE_NAMESERVERS = {"ana.ns.cloudflare.com": "172.64.32.1", "bob.ns.cloudflare.com": "108.162.192.1"}
CLOUDFLARE_HOST = {
    "name": "Cloudflare",
    "dns_settings_url": "https://dash.cloudflare.com/?to=/:account/:zone/dns/records",
}
ROUTE_53_HOST = {"name": "Route 53", "dns_settings_url": "https://console.aws.amazon.com/route53/v2/hostedzones"}
APPLY_URL_FAILED = "Error generating apply URL. Please try again later or contact support."
SIGNING_UNAVAILABLE = (
    "Automatic DNS configuration is temporarily unavailable for this provider. "
    "Please configure your DNS records manually."
)
DISCOVERY_RECORD = f"_domainconnect.{ROOT_DOMAIN}"
DMARC_LOOKUP = dns_operation(f"_dmarc.{DOMAIN}", "TXT")


@override_settings(DOMAIN_CONNECT_PRIVATE_KEY=domain_connect_signing_key_pem(), CLOUD_DEPLOYMENT="US")
class EmailDomainConnectTestCase(EmailDomainApiTestCase):
    zone_nameservers = CLOUDFLARE_NAMESERVERS

    def setUp(self) -> None:
        super().setUp()
        self.world.domain_connect.host(ROOT_DOMAIN)

    def check(self, domain: str = DOMAIN) -> dict[str, Any]:
        response = self.client.get(
            f"/api/projects/{self.team.id}/integrations/domain-connect/check", {"domain": domain}
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    def apply_url(self, sender: int, *, redirect_host: str = "us.posthog.com") -> Any:
        return self.client.post(
            f"/api/projects/{self.team.id}/integrations/domain-connect/apply-url",
            {
                "context": "email",
                "integration_id": sender,
                "redirect_uri": f"https://{redirect_host}/workflows/channels/email/{sender}?domain_connect=email",
            },
            format="json",
        )

    def config(self, sender: int) -> dict[str, Any]:
        return Integration.objects.get(id=sender).config


class TestOneClickEmailDomainSetup(EmailDomainConnectTestCase):
    @parameterized.expand(
        [
            ("us_sender_on_a_subdomain", "US", DOMAIN, "us.posthog.com"),
            ("eu_sender_on_the_root_domain", "EU", ROOT_DOMAIN, "eu.posthog.com"),
        ]
    )
    def test_approved_setup_publishes_the_template_records_and_verifies_the_sender(
        self, _name: str, region: str, domain: str, redirect_host: str
    ) -> None:
        with self.settings(CLOUD_DEPLOYMENT=region):
            assert self.check(domain) == {
                "supported": True,
                "provider_name": "Cloudflare",
                "available_providers": [],
                "dns_host": CLOUDFLARE_HOST,
                "existing_email_tools": [],
            }
            sender = self.create_sender(f"hello@{domain}")

            response = self.apply_url(sender, redirect_host=redirect_host)
            assert response.status_code == status.HTTP_200_OK, response.json()
            redirect_uri = self.world.domain_connect.apply(response.json()["url"])

        assert redirect_uri == f"https://{redirect_host}/workflows/channels/email/{sender}?domain_connect=email"
        body = self.status_body(sender)
        assert (body["status"], body["verified"]) == ("verified", True)
        assert self.config(sender)["setup_method"] == "auto"
        assert self.verified_event_methods() == ["auto"]

    def test_approved_setup_keeps_an_existing_dmarc_record(self) -> None:
        existing_dmarc = "v=DMARC1; p=reject; rua=mailto:dmarc@example.com"
        self.world.dns.publish_txt(f"_dmarc.{DOMAIN}", existing_dmarc)
        sender = self.create_sender(f"hello@{DOMAIN}")

        self.world.domain_connect.apply(self.apply_url(sender).json()["url"])

        assert self.world.dns.txt_values(f"_dmarc.{DOMAIN}") == [existing_dmarc]
        assert self.status_body(sender)["status"] == "verified"

    @parameterized.expand(
        [
            ("dmarc_lookup_times_out", lambda world: world.faults.inject(DMARC_LOOKUP, DnsFault.TIMEOUT)),
            ("dmarc_lookup_fails", lambda world: world.faults.inject(DMARC_LOOKUP, DnsFault.SERVFAIL)),
            ("dmarc_record_is_not_utf8", lambda world: world.dns.publish(f"_dmarc.{DOMAIN}", "TXT", '"\\255"')),
        ]
    )
    def test_approved_setup_leaves_dmarc_alone_when_an_existing_record_cannot_be_ruled_out(
        self, _name: str, arrange: Callable[[EmailDomainWorld], None]
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        arrange(self.world)

        self.world.domain_connect.apply(self.apply_url(sender).json()["url"])
        self.world.faults.clear()

        published_dmarc = [
            b"".join(rdata.strings)
            for rdata in self.world.dns.answers(f"_dmarc.{DOMAIN}", "TXT")
            if isinstance(rdata, TXT)
        ]
        assert b"v=DMARC1; p=none;" not in published_dmarc
        assert self.world.dns.txt_values(f"_amazonses.{DOMAIN}") != []

    def test_returning_without_approving_publishes_nothing_and_manual_setup_still_verifies(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        assert self.apply_url(sender).status_code == status.HTTP_200_OK

        body = self.status_body(sender)
        assert (body["status"], self.world.dns.txt_values(f"_amazonses.{DOMAIN}")) == ("pending", [])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/integrations/{sender}/email",
            {"config": {**self.config(sender), "setup_method": "manual"}},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        self.publish(body["records"], *ALL_KINDS)

        assert self.status_body(sender)["status"] == "verified"
        assert self.verified_event_methods() == ["manual"]

    def test_asking_for_setup_on_an_already_published_domain_verifies_it_at_once(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        self.publish(self.records_to_publish(sender), *ALL_KINDS)

        assert self.apply_url(sender).status_code == status.HTTP_200_OK

        assert self.config(sender)["verified"] is True
        assert len(self.verified_events()) == 1
        assert self.status_body(sender)["verified"] is True
        assert len(self.verified_events()) == 1

    @parameterized.expand([("same_bounce_subdomain", "feedback", 0), ("new_bounce_subdomain", "bounce", 1)])
    def test_sender_update_stores_the_setup_method_and_writes_ses_only_for_a_new_bounce_subdomain(
        self, _name: str, mail_from_subdomain: str, expected_ses_writes: int
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        writes_before = self.world.ses.writes.count("set_identity_mail_from_domain")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/integrations/{sender}/email",
            {"config": {**self.config(sender), "mail_from_subdomain": mail_from_subdomain, "setup_method": "manual"}},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self.config(sender)["setup_method"] == "manual"
        assert self.world.ses.writes.count("set_identity_mail_from_domain") - writes_before == expected_ses_writes
        assert self.world.ses.identities[DOMAIN].mail_from_domain == f"{mail_from_subdomain}.{DOMAIN}"

    def test_sender_update_keeps_a_verification_written_after_the_sender_was_loaded(self) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        loaded_before_verification = Integration.objects.get(id=sender)
        Integration.objects.filter(id=sender).update(config={**self.config(sender), "verified": True})

        EmailIntegration(loaded_before_verification).update_native_integration(
            {"name": "Renamed", "setup_method": "manual"}, self.team.id
        )

        assert self.config(sender)["verified"] is True
        assert self.config(sender)["name"] == "Renamed"
        assert self.config(sender)["setup_method"] == "manual"


class TestDomainConnectChaos(EmailDomainConnectTestCase):
    @parameterized.expand(
        [
            ("discovery_lookup_times_out", dns_operation(DISCOVERY_RECORD, "TXT"), DnsFault.TIMEOUT),
            ("discovery_lookup_fails", dns_operation(DISCOVERY_RECORD, "TXT"), DnsFault.SERVFAIL),
            ("settings_answer_a_server_error", SETTINGS_OPERATION, HttpFault.SERVER_ERROR),
            ("settings_are_rate_limited", SETTINGS_OPERATION, HttpFault.RATE_LIMITED),
            ("settings_time_out", SETTINGS_OPERATION, HttpFault.TIMEOUT),
            ("settings_answer_malformed_json", SETTINGS_OPERATION, HttpFault.MALFORMED_JSON),
        ]
    )
    def test_transient_provider_failure_falls_back_to_manual_setup_and_recovers(
        self, _name: str, operation: str, fault: DnsFault | HttpFault
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        config_before = self.config(sender)
        self.world.faults.inject(operation, fault)

        assert self.check()["supported"] is False
        response = self.apply_url(sender)

        assert (response.status_code, response.json()["detail"]) == (status.HTTP_400_BAD_REQUEST, APPLY_URL_FAILED)
        assert self.config(sender) == config_before

        self.world.faults.clear()
        assert self.check()["supported"] is True
        assert self.apply_url(sender).status_code == status.HTTP_200_OK
        assert self.config(sender)["setup_method"] == "auto"

    @parameterized.expand(
        [
            (
                "no_discovery_record",
                lambda test: test.world.dns.unpublish(DISCOVERY_RECORD, "TXT"),
                False,
                APPLY_URL_FAILED,
            ),
            (
                "discovery_record_does_not_exist",
                lambda test: test.world.faults.inject(dns_operation(DISCOVERY_RECORD, "TXT"), DnsFault.NXDOMAIN),
                False,
                APPLY_URL_FAILED,
            ),
            (
                "unsupported_provider",
                lambda test: (
                    test.world.dns.unpublish(DISCOVERY_RECORD, "TXT")
                    or test.world.dns.publish_txt(DISCOVERY_RECORD, "domainconnect.unsupported-dns.example")
                ),
                False,
                APPLY_URL_FAILED,
            ),
            (
                "settings_without_a_sync_url",
                lambda test: test.world.faults.inject(SETTINGS_OPERATION, HttpFault.MISSING_URL_SYNC_UX),
                False,
                APPLY_URL_FAILED,
            ),
            (
                "signing_key_missing",
                lambda test: test.enterContext(override_settings(DOMAIN_CONNECT_PRIVATE_KEY=None)),
                True,
                SIGNING_UNAVAILABLE,
            ),
        ]
    )
    def test_unusable_provider_answers_400_and_leaves_the_sender_unchanged(
        self, _name: str, arrange: Callable[[EmailDomainConnectTestCase], object], supported: bool, detail: str
    ) -> None:
        sender = self.create_sender(f"hello@{DOMAIN}")
        config_before = self.config(sender)
        arrange(self)

        check = self.check()
        response = self.apply_url(sender)

        assert (check["supported"], bool(check["available_providers"])) == (supported, not supported)
        assert (response.status_code, response.json()["detail"]) == (status.HTTP_400_BAD_REQUEST, detail)
        assert self.config(sender) == config_before


@override_settings(SES_REGION="us-east-1")
class TestDomainConnectCheckDetectsTheDnsHost(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.world = self.enterContext(EmailDomainWorld().installed())

    def check(self, domain: str) -> dict[str, Any]:
        response = self.client.get(
            f"/api/projects/{self.team.id}/integrations/domain-connect/check", {"domain": domain}
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()

    @parameterized.expand(
        [
            ("cloudflare", CLOUDFLARE_NAMESERVERS, CLOUDFLARE_HOST),
            ("route_53", {"ns-1536.awsdns-00.co.uk": "205.251.198.0"}, ROUTE_53_HOST),
            ("unknown_host", {"ns1.example-dns.net": "34.120.0.1"}, None),
        ]
    )
    def test_names_the_dns_host_from_the_root_domains_nameservers(
        self, _name: str, nameservers: dict[str, str], expected_host: dict[str, str] | None
    ) -> None:
        self.world.dns.add_zone(ROOT_DOMAIN, nameservers=nameservers)

        assert self.check(DOMAIN)["dns_host"] == expected_host

    def test_lists_the_email_tools_already_sending_for_the_root_domain_and_caches_them(self) -> None:
        self.world.dns.add_zone(ROOT_DOMAIN, nameservers=CLOUDFLARE_NAMESERVERS)
        self.world.dns.publish_txt(ROOT_DOMAIN, "v=spf1 include:sendgrid.net include:_spf.google.com ~all")
        self.world.dns.publish(f"k1._domainkey.{ROOT_DOMAIN}", "CNAME", "dkim.mcsv.net.")
        self.world.dns.publish_txt(f"resend._domainkey.{ROOT_DOMAIN}", "p=MIGfMA0GCSqGSIb3DQEB")

        assert self.check(DOMAIN)["existing_email_tools"] == ["Mailchimp", "SendGrid", "Resend"]

        self.world.dns.unpublish(ROOT_DOMAIN, "TXT")
        assert self.check(DOMAIN)["existing_email_tools"] == ["Mailchimp", "SendGrid", "Resend"]

    @parameterized.expand(
        [
            ("nameserver_lookup", ROOT_DOMAIN, "NS", "dns_host", CLOUDFLARE_HOST),
            ("spf_lookup", ROOT_DOMAIN, "TXT", "existing_email_tools", ["SendGrid"]),
        ]
    )
    def test_failed_lookup_answers_empty_and_is_retried_on_the_next_check(
        self, _name: str, name: str, rdtype: str, field: str, recovered: Any
    ) -> None:
        self.world.dns.add_zone(ROOT_DOMAIN, nameservers=CLOUDFLARE_NAMESERVERS)
        self.world.dns.publish_txt(ROOT_DOMAIN, "v=spf1 include:sendgrid.net ~all")
        self.world.faults.inject(dns_operation(name, rdtype), DnsFault.TIMEOUT)

        assert not self.check(DOMAIN)[field]

        self.world.faults.clear()
        assert self.check(DOMAIN)[field] == recovered
