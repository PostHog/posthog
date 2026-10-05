import logging
import ipaddress
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import dns.rdata
import dns.resolver
import dns.exception
from dns.rdtypes.ANY.CNAME import CNAME
from dns.rdtypes.ANY.MX import MX
from dns.rdtypes.ANY.NS import NS
from dns.rdtypes.ANY.TXT import TXT
from dns.rdtypes.IN.A import A

from posthog.dataclasses import frozen

from products.workflows.backend.facade.contracts import EmailDomainStatusRecord
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind as Kind,
    EmailDomainSetupRecordType as RecordType,
)

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 3
MAX_AUTHORITATIVE_NAMESERVERS = 2
ABSENT_ERRORS = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)


@frozen
class _Lookup:
    name: str
    type: RecordType


@frozen
class PublishedRecords:
    records: frozenset[EmailDomainStatusRecord]
    unanswered: frozenset[EmailDomainStatusRecord] = frozenset()

    @property
    def every_lookup_answered(self) -> bool:
        return not self.unanswered


# The zone's own nameservers answer first because public resolvers cache a negative answer for the
# zone's SOA minimum TTL, which hides a record the customer just added for up to an hour. A public
# resolver then checks what they could not confirm, because they cannot follow a CNAME to another
# zone, such as a DMARC record hosted by a DMARC reporting service.
def find_published_records(domain: str, records: Sequence[EmailDomainStatusRecord]) -> PublishedRecords:
    authoritative = _authoritative_resolver(domain)
    from_zone = _published_with(authoritative, records) if authoritative else PublishedRecords(records=frozenset())
    from_public = _published_with(_system_resolver(), [record for record in records if record not in from_zone.records])
    return PublishedRecords(records=from_zone.records | from_public.records, unanswered=from_public.unanswered)


def _published_with(resolver: dns.resolver.Resolver, records: Sequence[EmailDomainStatusRecord]) -> PublishedRecords:
    if not records:
        return PublishedRecords(records=frozenset())
    lookups = {_lookup_for(record) for record in records}
    with ThreadPoolExecutor(max_workers=len(lookups)) as pool:
        answers = dict(zip(lookups, pool.map(lambda lookup: _resolve(resolver, lookup), lookups)))
    return PublishedRecords(
        records=frozenset(record for record in records if _is_published(record, answers[_lookup_for(record)] or [])),
        unanswered=frozenset(record for record in records if answers[_lookup_for(record)] is None),
    )


def _lookup_for(record: EmailDomainStatusRecord) -> _Lookup:
    return _Lookup(name=record.hostname, type=record.type)


def _system_resolver() -> dns.resolver.Resolver:
    resolver = dns.resolver.Resolver()
    resolver.lifetime = LOOKUP_TIMEOUT_SECONDS
    return resolver


def _authoritative_resolver(domain: str) -> dns.resolver.Resolver | None:
    system = _system_resolver()
    try:
        zone = dns.resolver.zone_for_name(domain, resolver=system, lifetime=LOOKUP_TIMEOUT_SECONDS)
        nameservers = [rdata.target for rdata in system.resolve(zone, "NS") if isinstance(rdata, NS)]
        addresses = [
            rdata.address
            for nameserver in nameservers[:MAX_AUTHORITATIVE_NAMESERVERS]
            for rdata in system.resolve(nameserver, "A")
            if isinstance(rdata, A) and _is_public_address(rdata.address)
        ]
    except dns.exception.DNSException:
        return None
    if not addresses:
        return None
    authoritative = dns.resolver.Resolver(configure=False)
    authoritative.nameservers = addresses
    authoritative.lifetime = LOOKUP_TIMEOUT_SECONDS
    return authoritative


# The customer controls the zone's NS records, so they could point our queries at internal addresses.
def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


def _resolve(resolver: dns.resolver.Resolver, lookup: _Lookup) -> list[str] | None:
    try:
        answers = resolver.resolve(lookup.name, lookup.type.value)
    except ABSENT_ERRORS:
        return []
    except dns.exception.DNSException:
        logger.info("No DNS answer for %s %s", lookup.type.value, lookup.name, exc_info=True)
        return None
    return [answer for rdata in answers if (answer := _normalized_answer(rdata)) is not None]


def _normalized_answer(rdata: dns.rdata.Rdata) -> str | None:
    if isinstance(rdata, TXT):
        return b"".join(rdata.strings).decode("utf-8", errors="replace").strip().strip('"')
    if isinstance(rdata, CNAME):
        return _normalized_hostname(rdata.target.to_text())
    if isinstance(rdata, MX):
        return f"{rdata.preference} {_normalized_hostname(rdata.exchange.to_text())}"
    return None


def _normalized_hostname(hostname: str) -> str:
    return hostname.lower().rstrip(".")


def _is_published(record: EmailDomainStatusRecord, answers: list[str]) -> bool:
    match record.kind, record.type:
        case Kind.DMARC, _:
            return any(answer.lower().startswith("v=dmarc1") for answer in answers)
        case Kind.SPF | Kind.MAIL_FROM_SPF, _:
            return any(_spf_includes(answer, record.value) for answer in answers)
        case _, RecordType.CNAME:
            return _normalized_hostname(record.value) in answers
        case _, RecordType.MX:
            return f"{record.priority} {_normalized_hostname(record.value)}" in answers
        case _:
            return record.value in answers


# A domain can publish only one SPF record, so SES's mechanism usually sits next to another
# sender's. The record counts as published when it carries every include the expected one does.
def _spf_includes(published: str, expected: str) -> bool:
    published_terms = published.lower().split()
    if not published_terms or published_terms[0] != "v=spf1":
        return False
    expected_includes = {term for term in expected.lower().split() if term.startswith("include:")}
    return expected_includes.issubset(published_terms)
