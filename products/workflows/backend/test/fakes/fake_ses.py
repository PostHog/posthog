from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from unittest.mock import patch

from botocore.exceptions import ClientError
from dns.rdtypes.ANY.MX import MX

from posthog.dataclasses import frozen

from products.workflows.backend.test.fakes.fake_dns import FakeDnsZone
from products.workflows.backend.test.fakes.faults import AwsFault, FaultInjector

ACCOUNT_ID = "123456789012"
SUCCESS = "Success"
PENDING = "Pending"


@frozen(frozen=False)
class SesIdentity:
    domain: str
    verification_token: str | None
    dkim_tokens: tuple[str, ...] = ()
    mail_from_domain: str | None = None
    forced_verification_status: str | None = None
    forced_dkim_status: str | None = None
    checks_paused: bool = False


class FakeSes:
    """SES v1, SESv2 tenants and STS behind `boto3.client`. Each read checks `FakeDnsZone` the way SES polls
    DNS, so a part flips to Success only once its records are published."""

    def __init__(self, dns: FakeDnsZone, faults: FaultInjector, *, region: str = "us-east-1") -> None:
        self._dns = dns
        self._faults = faults
        self.region = region
        self.identities: dict[str, SesIdentity] = {}
        self.tenant_resources: dict[str, set[str]] = {}
        self.writes: list[str] = []

    @contextmanager
    def installed(self) -> Iterator["FakeSes"]:
        with patch("boto3.client", self._client):
            yield self

    def add_identity(self, domain: str, **fields: Any) -> SesIdentity:
        identity = SesIdentity(domain=domain, **{"verification_token": f"token-{domain}", **fields})
        self.identities[domain] = identity
        return identity

    def associate(self, domain: str, tenant: str) -> None:
        self.tenant_resources.setdefault(tenant, set()).add(self.identity_arn(domain))

    def transfer_identity(self, domain: str, tenant: str) -> None:
        for resources in self.tenant_resources.values():
            resources.discard(self.identity_arn(domain))
        self.associate(domain, tenant)

    def tenants_of(self, domain: str) -> set[str]:
        return {tenant for tenant, resources in self.tenant_resources.items() if self.identity_arn(domain) in resources}

    def identity_arn(self, domain: str) -> str:
        return f"arn:aws:ses:{self.region}:{ACCOUNT_ID}:identity/{domain}"

    def verification_status(self, identity: SesIdentity) -> str:
        if identity.checks_paused:
            return PENDING
        if identity.forced_verification_status:
            return identity.forced_verification_status
        published = identity.verification_token in self._dns.txt_values(f"_amazonses.{identity.domain}")
        return SUCCESS if published else PENDING

    def dkim_status(self, identity: SesIdentity) -> str:
        if identity.checks_paused:
            return PENDING
        if identity.forced_dkim_status:
            return identity.forced_dkim_status
        if not identity.dkim_tokens:
            return "NotStarted"
        published = all(
            self._dns.cname_target(f"{token}._domainkey.{identity.domain}") == f"{token}.dkim.amazonses.com"
            for token in identity.dkim_tokens
        )
        return SUCCESS if published else PENDING

    def mail_from_status(self, identity: SesIdentity) -> str:
        assert identity.mail_from_domain is not None
        if identity.checks_paused:
            return PENDING
        expected_exchange = f"feedback-smtp.{self.region}.amazonses.com."
        exchanges = [
            rdata.exchange.to_text()
            for rdata in self._dns.answers(identity.mail_from_domain, "MX")
            if isinstance(rdata, MX)
        ]
        # SES rejects a MAIL FROM domain that has any MX record besides its own.
        return SUCCESS if exchanges == [expected_exchange] else PENDING

    def _client(self, service_name: str, **_config: Any) -> "_FakeAwsClient":
        handlers: dict[str, dict[str, Callable[..., Any]]] = {
            "ses": {
                "verify_domain_identity": self._verify_domain_identity,
                "verify_domain_dkim": self._verify_domain_dkim,
                "set_identity_mail_from_domain": self._set_identity_mail_from_domain,
                "get_identity_verification_attributes": self._get_identity_verification_attributes,
                "get_identity_dkim_attributes": self._get_identity_dkim_attributes,
                "get_identity_mail_from_domain_attributes": self._get_identity_mail_from_domain_attributes,
            },
            "sesv2": {
                "create_tenant": self._create_tenant,
                "create_tenant_resource_association": self._create_tenant_resource_association,
                "list_resource_tenants": self._list_resource_tenants,
            },
            "sts": {"get_caller_identity": lambda: {"Account": ACCOUNT_ID}},
        }
        if service_name not in handlers:
            raise ValueError(f"FakeSes does not serve the {service_name} client")
        return _FakeAwsClient(service_name, handlers[service_name], self._faults)

    def _verify_domain_identity(self, *, Domain: str) -> dict[str, Any]:
        self.writes.append("verify_domain_identity")
        identity = self.identities.get(Domain) or self.add_identity(Domain)
        return {"VerificationToken": identity.verification_token}

    def _verify_domain_dkim(self, *, Domain: str) -> dict[str, Any]:
        self.writes.append("verify_domain_dkim")
        identity = self.identities.get(Domain) or self.add_identity(Domain)
        if not identity.dkim_tokens:
            identity.dkim_tokens = tuple(f"dk{index}{Domain.replace('.', '')}" for index in range(1, 4))
        return {"DkimTokens": list(identity.dkim_tokens)}

    def _set_identity_mail_from_domain(self, *, Identity: str, MailFromDomain: str, **_options: Any) -> dict:
        self.writes.append("set_identity_mail_from_domain")
        self._existing(Identity, "SetIdentityMailFromDomain").mail_from_domain = MailFromDomain
        return {}

    def _get_identity_verification_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "VerificationAttributes": {
                identity.domain: {
                    "VerificationStatus": self.verification_status(identity),
                    **({"VerificationToken": identity.verification_token} if identity.verification_token else {}),
                }
                for identity in self._known(Identities)
            }
        }

    def _get_identity_dkim_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "DkimAttributes": {
                identity.domain: {
                    "DkimEnabled": bool(identity.dkim_tokens),
                    "DkimVerificationStatus": self.dkim_status(identity),
                    **({"DkimTokens": list(identity.dkim_tokens)} if identity.dkim_tokens else {}),
                }
                for identity in self._known(Identities)
            }
        }

    def _get_identity_mail_from_domain_attributes(self, *, Identities: list[str]) -> dict[str, Any]:
        return {
            "MailFromDomainAttributes": {
                identity.domain: {
                    "MailFromDomain": identity.mail_from_domain,
                    "MailFromDomainStatus": self.mail_from_status(identity),
                    "BehaviorOnMXFailure": "UseDefaultValue",
                }
                for identity in self._known(Identities)
                if identity.mail_from_domain
            }
        }

    def _create_tenant(self, *, TenantName: str, **_options: Any) -> dict:
        self.writes.append("create_tenant")
        if TenantName in self.tenant_resources:
            raise ClientError({"Error": {"Code": "AlreadyExistsException"}}, "CreateTenant")
        self.tenant_resources[TenantName] = set()
        return {"TenantName": TenantName}

    def _create_tenant_resource_association(self, *, TenantName: str, ResourceArn: str) -> dict:
        self.writes.append("create_tenant_resource_association")
        resources = self.tenant_resources.setdefault(TenantName, set())
        if ResourceArn in resources:
            raise ClientError({"Error": {"Code": "AlreadyExistsException"}}, "CreateTenantResourceAssociation")
        resources.add(ResourceArn)
        return {}

    def _list_resource_tenants(self, *, ResourceArn: str) -> dict[str, Any]:
        return {
            "ResourceTenants": [
                {"TenantName": tenant, "ResourceArn": ResourceArn}
                for tenant, resources in sorted(self.tenant_resources.items())
                if ResourceArn in resources
            ]
        }

    def _known(self, domains: list[str]) -> list[SesIdentity]:
        return [self.identities[domain] for domain in domains if domain in self.identities]

    def _existing(self, domain: str, operation: str) -> SesIdentity:
        if domain not in self.identities:
            raise ClientError({"Error": {"Code": "InvalidParameterValue"}}, operation)
        return self.identities[domain]


class _FakeAwsClient:
    def __init__(self, service: str, handlers: dict[str, Callable[..., Any]], faults: FaultInjector) -> None:
        self._service = service
        self._handlers = handlers
        self._faults = faults

    def __getattr__(self, operation: str) -> Callable[..., Any]:
        if operation not in self._handlers:
            raise AttributeError(f"FakeSes {self._service} client has no {operation}")
        handler = self._handlers[operation]

        def call(**kwargs: Any) -> Any:
            fault = self._faults.fault_for(f"{self._service}.{operation}")
            if isinstance(fault, AwsFault):
                raise fault.error(operation)
            return handler(**kwargs)

        return call
