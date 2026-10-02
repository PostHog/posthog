from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import cache
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from products.workflows.backend.test.fakes.fake_dns import FakeDnsZone
from products.workflows.backend.test.fakes.fake_domain_connect import FakeDomainConnectProvider
from products.workflows.backend.test.fakes.fake_ses import FakeSes
from products.workflows.backend.test.fakes.faults import FaultInjector


class EmailDomainWorld:
    """Everything outside PostHog that the email domain setup talks to, sharing one DNS and one fault injector."""

    def __init__(self) -> None:
        self.faults = FaultInjector()
        self.dns = FakeDnsZone(self.faults)
        self.ses = FakeSes(self.dns, self.faults)
        self.domain_connect = FakeDomainConnectProvider(self.dns, self.faults)

    @contextmanager
    def installed(self) -> Iterator["EmailDomainWorld"]:
        with self.dns.installed(), self.ses.installed(), self.domain_connect.installed():
            yield self

    def publish_record(self, record: Mapping[str, Any]) -> None:
        """Publishes one record from the status API the way a person copies it into their DNS host."""
        hostname, value = record["hostname"], record["value"]
        match record["type"]:
            case "TXT":
                self.dns.publish_txt(hostname, value)
            case "CNAME":
                self.dns.publish(hostname, "CNAME", f"{value}.")
            case "MX":
                self.dns.publish(hostname, "MX", f"{record['priority']} {value}.")


@cache
def domain_connect_signing_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
