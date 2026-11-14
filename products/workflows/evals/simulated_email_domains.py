from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from django.conf import settings
from django.test import override_settings

from posthog.dataclasses import frozen

from products.workflows.backend.tests.fakes.fake_ses import dkim_tokens, verification_token
from products.workflows.backend.tests.fakes.world import EmailDomainWorld, domain_connect_signing_key_pem

__all__ = [
    "DOMAIN_CONNECT_ROOT_DOMAIN",
    "MX_PRIORITY",
    "SES_SPF_VALUE",
    "SIMULATED_EMAIL_DOMAINS",
    "DnsRecord",
    "SimulatedEmailDomains",
    "mail_from_mx_host",
    "ses_records",
    "simulated_email_domains",
]

SIMULATED_ROOT_DOMAINS = ("example.com", "example.net", "example.org")
DOMAIN_CONNECT_ROOT_DOMAIN = "example.net"
OTHER_ORGANIZATION_TENANT = "team-0"
SES_SPF_VALUE = "v=spf1 include:amazonses.com ~all"
MX_PRIORITY = 10


@frozen
class DnsRecord:
    name: str
    record_type: str
    value: str


def mail_from_mx_host() -> str:
    return f"feedback-smtp.{settings.SES_REGION}.amazonses.com"


def ses_records(domain: str, mail_from_subdomain: str = "feedback") -> list[DnsRecord]:
    mail_from_domain = f"{mail_from_subdomain}.{domain}"
    return [
        DnsRecord(name=f"_amazonses.{domain}", record_type="TXT", value=verification_token(domain)),
        *(
            DnsRecord(name=f"{token}._domainkey.{domain}", record_type="CNAME", value=f"{token}.dkim.amazonses.com")
            for token in dkim_tokens(domain)
        ),
        DnsRecord(name=domain, record_type="TXT", value=SES_SPF_VALUE),
        DnsRecord(name=mail_from_domain, record_type="MX", value=mail_from_mx_host()),
        DnsRecord(name=mail_from_domain, record_type="TXT", value=SES_SPF_VALUE),
        DnsRecord(name=f"_dmarc.{domain}", record_type="TXT", value="v=DMARC1; p=none;"),
    ]


class SimulatedEmailDomains(EmailDomainWorld):
    def __init__(self) -> None:
        super().__init__()
        self.ses.region = settings.SES_REGION
        for root_domain in SIMULATED_ROOT_DOMAINS:
            self.dns.add_zone(root_domain)
        self.domain_connect.host(DOMAIN_CONNECT_ROOT_DOMAIN)

    def publish(self, records: Iterable[DnsRecord]) -> None:
        for record in records:
            self.publish_record(
                {"hostname": record.name, "type": record.record_type, "value": record.value, "priority": MX_PRIORITY}
            )

    def verify_for_team(self, team_id: int, domain: str, mail_from_subdomain: str) -> None:
        self.publish(ses_records(domain, mail_from_subdomain))
        self.ses.add_identity(
            domain, dkim_tokens=dkim_tokens(domain), mail_from_domain=f"{mail_from_subdomain}.{domain}"
        )
        self.ses.associate(domain, f"team-{team_id}")

    def claim_for_other_organization(self, domain: str) -> None:
        self.ses.associate(domain, OTHER_ORGANIZATION_TENANT)


SIMULATED_EMAIL_DOMAINS = SimulatedEmailDomains()


@contextmanager
def simulated_email_domains() -> Iterator[SimulatedEmailDomains]:
    signing_key = settings.DOMAIN_CONNECT_PRIVATE_KEY or domain_connect_signing_key_pem()
    with override_settings(DOMAIN_CONNECT_PRIVATE_KEY=signing_key), SIMULATED_EMAIL_DOMAINS.installed(passthrough=True):
        yield SIMULATED_EMAIL_DOMAINS
