"""Simulated SES, DNS and Domain Connect for the email domain eval suite.

The agent drives the real API through MCP, and the real SES provider code builds the
DNS records and statuses it reads. Only the network edges are replaced: the boto3
clients, DNS answers for the reserved example domains, and the Domain Connect provider
settings. Each case publishes its own records, so every status the agent sees follows
from what the case seeded, the same way it follows from a real DNS zone.
"""

from __future__ import annotations

import uuid
import hashlib
import threading
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, cast

from unittest.mock import patch

from django.conf import settings
from django.core.cache.backends.locmem import LocMemCache

import dns.rdata
import dns.resolver
import dns.rdatatype
import dns.rdataclass
from cryptography.hazmat.primitives.asymmetric import rsa

from posthog import domain_connect
from posthog.dataclasses import frozen

from products.workflows.backend import providers
from products.workflows.backend.facade.contracts import EmailDomainVerification
from products.workflows.backend.providers.ses import SESProvider

__all__ = [
    "DOMAIN_CONNECT_ROOT_DOMAIN",
    "DOMAIN_CONNECT_SYNC_UX",
    "MX_PRIORITY",
    "SES_SPF_VALUE",
    "SIMULATED_EMAIL_DOMAINS",
    "DnsRecord",
    "SimulatedEmailDomains",
    "SimulatedSESProvider",
    "dkim_tokens",
    "mail_from_mx_host",
    "publish_domain_connect_support",
    "ses_records",
    "simulated_email_domains",
    "verification_token",
]

SIMULATED_ROOT_DOMAINS = ("example.com", "example.net", "example.org")
DOMAIN_CONNECT_ROOT_DOMAIN = "example.net"
DOMAIN_CONNECT_ENDPOINT = next(
    endpoint
    for endpoint, name in domain_connect.DOMAIN_CONNECT_PROVIDERS.items()
    if name == domain_connect.DomainConnectProviderName.CLOUDFLARE
)
DOMAIN_CONNECT_SYNC_UX = "https://dash.cloudflare.com/domainconnect"
SES_SPF_VALUE = "v=spf1 include:amazonses.com ~all"
MX_PRIORITY = 10


@frozen
class DnsRecord:
    name: str
    record_type: str
    value: str


def _digest(purpose: str, domain: str) -> str:
    return hashlib.sha256(f"{purpose}:{domain}".encode()).hexdigest()


def verification_token(domain: str) -> str:
    return _digest("verification", domain)[:44]


def dkim_tokens(domain: str) -> list[str]:
    return [_digest(f"dkim-{index}", domain)[:32] for index in range(3)]


def mail_from_mx_host() -> str:
    return f"feedback-smtp.{settings.SES_REGION}.amazonses.com"


def _ownership_record(domain: str) -> DnsRecord:
    return DnsRecord(name=f"_amazonses.{domain}", record_type="TXT", value=verification_token(domain))


def _dkim_records(domain: str) -> list[DnsRecord]:
    return [
        DnsRecord(name=f"{token}._domainkey.{domain}", record_type="CNAME", value=f"{token}.dkim.amazonses.com")
        for token in dkim_tokens(domain)
    ]


def _mail_from_mx_record(mail_from_domain: str) -> DnsRecord:
    return DnsRecord(name=mail_from_domain, record_type="MX", value=mail_from_mx_host())


def ses_records(domain: str, mail_from_subdomain: str = "feedback") -> list[DnsRecord]:
    """Every record SES asks for, with the values the simulated SES issues for `domain`."""
    mail_from_domain = f"{mail_from_subdomain}.{domain}"
    return [
        _ownership_record(domain),
        *_dkim_records(domain),
        DnsRecord(name=domain, record_type="TXT", value=SES_SPF_VALUE),
        _mail_from_mx_record(mail_from_domain),
        DnsRecord(name=mail_from_domain, record_type="TXT", value=SES_SPF_VALUE),
        DnsRecord(name=f"_dmarc.{domain}", record_type="TXT", value="v=DMARC1; p=none;"),
    ]


def _normalize(name: str) -> str:
    return name.rstrip(".").lower()


def _tenant_name(team_id: int) -> str:
    return f"team-{team_id}"


class SimulatedEmailDomains:
    """The DNS zones and SES tenant ownership every simulated call reads.

    Seeders write it and the live server's request threads read it, so access is locked.
    Tenant ownership is keyed by team, so a case only owns the identities its own team
    created, the way SES tenants scope them.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str], set[str]] = {}
        self._other_organization_domains: set[str] = set()
        self._team_domains: set[tuple[int, str]] = set()
        self._mail_from_domains: dict[str, str] = {}

    def covers(self, name: str) -> bool:
        normalized = _normalize(name)
        return any(normalized == root or normalized.endswith(f".{root}") for root in SIMULATED_ROOT_DOMAINS)

    def publish(self, records: Iterable[DnsRecord]) -> None:
        with self._lock:
            for record in records:
                self._records.setdefault((_normalize(record.name), record.record_type), set()).add(record.value)

    def answers(self, name: str, record_type: str) -> set[str]:
        with self._lock:
            return set(self._records.get((_normalize(name), record_type), set()))

    def claim_for_other_organization(self, domain: str) -> None:
        with self._lock:
            self._other_organization_domains.add(_normalize(domain))

    def associate(self, team_id: int, domain: str) -> None:
        with self._lock:
            self._team_domains.add((team_id, _normalize(domain)))

    def disassociate(self, team_id: int, domain: str) -> None:
        with self._lock:
            self._team_domains.discard((team_id, _normalize(domain)))

    def tenants(self, domain: str, team_id: int | None) -> set[str]:
        normalized = _normalize(domain)
        with self._lock:
            tenants = {"team-0"} if normalized in self._other_organization_domains else set()
            if team_id is not None and (team_id, normalized) in self._team_domains:
                tenants.add(_tenant_name(team_id))
            return tenants

    def set_mail_from_domain(self, domain: str, mail_from_domain: str) -> None:
        with self._lock:
            self._mail_from_domains[_normalize(domain)] = mail_from_domain

    def mail_from_domain(self, domain: str) -> str | None:
        with self._lock:
            return self._mail_from_domains.get(_normalize(domain))

    def is_published(self, record: DnsRecord) -> bool:
        return record.value in self.answers(record.name, record.record_type)


SIMULATED_EMAIL_DOMAINS = SimulatedEmailDomains()


def _domain_from_identity_arn(arn: str) -> str | None:
    _, separator, identity = arn.partition(":identity/")
    return identity if separator else None


class _SimulatedSes:
    def __init__(self, domains: SimulatedEmailDomains) -> None:
        self._domains = domains

    def verify_domain_identity(self, *, Domain: str) -> dict[str, Any]:
        return {"VerificationToken": verification_token(Domain)}

    def verify_domain_dkim(self, *, Domain: str) -> dict[str, Any]:
        return {"DkimTokens": dkim_tokens(Domain)}

    def set_identity_mail_from_domain(self, *, Identity: str, MailFromDomain: str, **_: Any) -> dict[str, Any]:
        self._domains.set_mail_from_domain(Identity, MailFromDomain)
        return {}

    def delete_identity(self, *, Identity: str) -> dict[str, Any]:
        return {}

    def get_identity_verification_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "VerificationAttributes": {
                domain: {"VerificationStatus": self._status([_ownership_record(domain)])} for domain in Identities
            }
        }

    def get_identity_dkim_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "DkimAttributes": {
                domain: {"DkimVerificationStatus": self._status(_dkim_records(domain))} for domain in Identities
            }
        }

    def get_identity_mail_from_domain_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "MailFromDomainAttributes": {
                domain: {"MailFromDomainStatus": self._status([_mail_from_mx_record(mail_from_domain)])}
                for domain in Identities
                if (mail_from_domain := self._domains.mail_from_domain(domain))
            }
        }

    def _status(self, required: list[DnsRecord]) -> str:
        return "Success" if all(self._domains.is_published(record) for record in required) else "Pending"


class _SimulatedSesV2:
    def __init__(self, domains: SimulatedEmailDomains) -> None:
        self._domains = domains
        self.team_id: int | None = None

    def list_resource_tenants(self, *, ResourceArn: str) -> dict[str, Any]:
        domain = _domain_from_identity_arn(ResourceArn) or ""
        return {
            "ResourceTenants": [{"TenantName": name} for name in sorted(self._domains.tenants(domain, self.team_id))]
        }

    def create_tenant(self, **_: Any) -> dict[str, Any]:
        return {}

    def create_tenant_resource_association(self, *, TenantName: str, ResourceArn: str) -> dict[str, Any]:
        domain = _domain_from_identity_arn(ResourceArn)
        if domain and self.team_id is not None and TenantName == _tenant_name(self.team_id):
            self._domains.associate(self.team_id, domain)
        return {}

    def delete_tenant_resource_association(self, *, TenantName: str, ResourceArn: str) -> dict[str, Any]:
        domain = _domain_from_identity_arn(ResourceArn)
        if domain and self.team_id is not None:
            self._domains.disassociate(self.team_id, domain)
        return {}


class _SimulatedSts:
    def get_caller_identity(self) -> dict[str, Any]:
        return {"Account": "000000000000"}


class SimulatedSESProvider(SESProvider):
    """The real SES provider logic on top of simulated AWS clients."""

    def __init__(self, domains: SimulatedEmailDomains) -> None:
        self._simulated_v2 = _SimulatedSesV2(domains)
        self.sts_client = cast(Any, _SimulatedSts())
        self.ses_client = cast(Any, _SimulatedSes(domains))
        self.ses_v2_client = cast(Any, self._simulated_v2)
        self.ses_v2_metrics_client = self.ses_v2_client

    def create_email_domain(
        self, domain: str, mail_from_subdomain: str, team_id: int, org_team_ids: Iterable[int] | None = None
    ) -> None:
        self._simulated_v2.team_id = team_id
        super().create_email_domain(domain, mail_from_subdomain, team_id, org_team_ids)

    def verify_email_domain(self, domain: str, mail_from_subdomain: str, team_id: int) -> EmailDomainVerification:
        self._simulated_v2.team_id = team_id
        return super().verify_email_domain(domain, mail_from_subdomain, team_id)


def _rdata(record_type: str, value: str) -> dns.rdata.Rdata:
    text = {
        "TXT": '"{}"'.format(value.replace('"', '\\"')),
        "CNAME": f"{value}.",
        "MX": f"{MX_PRIORITY} {value}.",
    }[record_type]
    return dns.rdata.from_text(dns.rdataclass.IN, dns.rdatatype.from_text(record_type), text)


def _simulated_answers(domains: SimulatedEmailDomains, qname: Any, rdtype: Any) -> list[dns.rdata.Rdata]:
    record_type = dns.rdatatype.to_text(dns.rdatatype.RdataType.make(rdtype))
    values = domains.answers(str(qname), record_type)
    if not values:
        raise dns.resolver.NXDOMAIN()
    return [_rdata(record_type, value) for value in sorted(values)]


@contextmanager
def simulated_email_domains(domains: SimulatedEmailDomains = SIMULATED_EMAIL_DOMAINS) -> Iterator[None]:
    """Route SES, DNS and Domain Connect calls for the example domains through `domains`.

    Lookups for any other name reach the real resolver, so suites running alongside this
    one in the same process keep working. Their Domain Connect lookups use a fresh cache
    while this runs, which costs a repeated lookup and nothing else.
    """
    original_resolver_method = dns.resolver.Resolver.resolve
    original_resolve = dns.resolver.resolve
    original_fetch_settings = domain_connect._fetch_provider_settings
    original_signing_key = domain_connect.get_signing_key
    eval_signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def resolver_method(
        resolver: dns.resolver.Resolver, qname: Any, rdtype: Any = "A", *args: Any, **kwargs: Any
    ) -> list[dns.rdata.Rdata] | dns.resolver.Answer:
        if domains.covers(str(qname)):
            return _simulated_answers(domains, qname, rdtype)
        return original_resolver_method(resolver, qname, rdtype, *args, **kwargs)

    def resolve(
        qname: Any, rdtype: Any = "A", *args: Any, **kwargs: Any
    ) -> list[dns.rdata.Rdata] | dns.resolver.Answer:
        if domains.covers(str(qname)):
            return _simulated_answers(domains, qname, rdtype)
        return original_resolve(qname, rdtype, *args, **kwargs)

    def fetch_provider_settings(endpoint: str, domain: str) -> dict | None:
        if domains.covers(domain):
            return {"providerName": "Cloudflare", "urlSyncUX": DOMAIN_CONNECT_SYNC_UX}
        return original_fetch_settings(endpoint, domain)

    with ExitStack() as stack:
        stack.enter_context(patch.object(providers, "SESProvider", lambda: SimulatedSESProvider(domains)))
        stack.enter_context(patch.object(dns.resolver.Resolver, "resolve", resolver_method))
        stack.enter_context(patch.object(dns.resolver, "resolve", resolve))
        stack.enter_context(patch.object(domain_connect, "_fetch_provider_settings", fetch_provider_settings))
        stack.enter_context(
            patch.object(domain_connect, "get_signing_key", lambda: original_signing_key() or eval_signing_key)
        )
        # Discovery caches each domain for an hour, and LocMemCache instances with the same
        # name share one store, so each simulation gets a store no earlier lookup has filled.
        stack.enter_context(
            patch.object(domain_connect, "cache", LocMemCache(f"email-domain-evals-{uuid.uuid4()}", {}))
        )
        yield


def publish_domain_connect_support(domains: SimulatedEmailDomains = SIMULATED_EMAIL_DOMAINS) -> None:
    domains.publish(
        [
            DnsRecord(
                name=f"_domainconnect.{DOMAIN_CONNECT_ROOT_DOMAIN}", record_type="TXT", value=DOMAIN_CONNECT_ENDPOINT
            )
        ]
    )
