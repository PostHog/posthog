import re
import logging
import ipaddress
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import field, replace

import dns.rdata
import dns.resolver
import dns.exception
from dns.rdtypes.ANY.CNAME import CNAME
from dns.rdtypes.ANY.MX import MX
from dns.rdtypes.ANY.NS import NS
from dns.rdtypes.ANY.TXT import TXT
from dns.rdtypes.IN.A import A

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.domain_connect import organizational_domain
from posthog.security.oob_domains import matched_oob_domain

from products.workflows.backend.facade.contracts import EmailDomainStatusRecord
from products.workflows.backend.facade.enums import (
    EmailDomainSetupRecordKind as Kind,
    EmailDomainSetupRecordType as RecordType,
)

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 3
MAX_AUTHORITATIVE_NAMESERVERS = 2
MAX_PARALLEL_LOOKUPS = 8
ABSENT_ERRORS = (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer)
_DMARC_RECORD = re.compile(r"\s*[vV]\s*=\s*DMARC1(\s|;|\Z)")
_DMARC_VERSION = re.compile(r"[vV][ \t]*=[ \t]*DMARC1[ \t]*(;|\Z)")
_DMARC_REQUEST = r"none|quarantine|reject"
_DMARC_TEXT = re.compile(r"[\t\x20-\x7e]*")
_DMARC_TAG_NAME = re.compile(r"[a-z][a-z0-9_]*", re.IGNORECASE)
_DMARC_SHOWN_TAGS = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "p": _DMARC_REQUEST,
        "sp": _DMARC_REQUEST,
        "pct": r"100|0?[0-9]?[0-9]",
        "adkim": r"[rs]",
        "aspf": r"[rs]",
    }.items()
}


@frozen
class _Lookup:
    name: str
    type: RecordType


@frozen
class PublishedRecords:
    records: frozenset[EmailDomainStatusRecord]
    unanswered: frozenset[EmailDomainStatusRecord] = frozenset()
    dmarc_policies: Mapping[EmailDomainStatusRecord, tuple[str, ...]] = field(default_factory=dict)

    @property
    def every_lookup_answered(self) -> bool:
        return not self.unanswered


# The zone's own nameservers answer first because public resolvers cache a negative answer for the
# zone's SOA minimum TTL, which hides a record the customer just added for up to an hour. A public
# resolver then checks what they could not confirm, because they cannot follow a CNAME to another
# zone, such as a DMARC record hosted by a DMARC reporting service.
def find_published_records(domain: str, records: Sequence[EmailDomainStatusRecord]) -> PublishedRecords:
    if is_cloud() and (oob_domain := matched_oob_domain(domain)) is not None:
        logger.info("security.oob_domain_seen domain=%s guard=email_domain_dns", oob_domain)
        # The lookup alone confirms the path to whoever runs the collaborator, so the name is
        # refused rather than resolved. No record is published for it, so the domain never verifies.
        return PublishedRecords(records=frozenset())
    authoritative = _authoritative_resolver(domain)
    from_zone = _published_with(authoritative, records) if authoritative else PublishedRecords(records=frozenset())
    from_public = _published_with(_system_resolver(), [record for record in records if record not in from_zone.records])
    return PublishedRecords(
        records=from_zone.records | from_public.records,
        unanswered=from_public.unanswered,
        dmarc_policies={**from_zone.dmarc_policies, **from_public.dmarc_policies},
    )


def inherited_dmarc_record(domain: str, record: EmailDomainStatusRecord) -> EmailDomainStatusRecord | None:
    parent = organizational_domain(domain)
    if parent == domain:
        return None
    return replace(record, hostname=f"_dmarc.{parent}")


def dmarc_record_in_force(
    record: EmailDomainStatusRecord, inherited: EmailDomainStatusRecord | None, published: PublishedRecords
) -> tuple[EmailDomainStatusRecord, PublishedRecords]:
    probe = frozenset({inherited} if inherited else ())
    own = replace(published, records=published.records - probe, unanswered=published.unanswered - probe)
    if record in published.records:
        return _with_published_value(record, own)
    if inherited is None or record in published.unanswered or record in published.dmarc_policies:
        return record, own
    if inherited in published.records:
        return _with_published_value(inherited, own)
    if inherited in published.unanswered:
        return record, replace(own, unanswered=own.unanswered | {record})
    return record, own


def _with_published_value(
    record: EmailDomainStatusRecord, published: PublishedRecords
) -> tuple[EmailDomainStatusRecord, PublishedRecords]:
    in_force = replace(record, value=_policy_in_force(published.dmarc_policies[record][0]) or record.value)
    return in_force, replace(published, records=(published.records - {record}) | {in_force})


def _published_with(resolver: dns.resolver.Resolver, records: Sequence[EmailDomainStatusRecord]) -> PublishedRecords:
    if not records:
        return PublishedRecords(records=frozenset())
    lookups = {_lookup_for(record) for record in records}
    with ThreadPoolExecutor(max_workers=min(len(lookups), MAX_PARALLEL_LOOKUPS)) as pool:
        answers = dict(zip(lookups, pool.map(lambda lookup: _resolve(resolver, lookup), lookups)))
    published = frozenset(record for record in records if _is_published(record, answers[_lookup_for(record)] or []))
    return PublishedRecords(
        records=published,
        unanswered=frozenset(record for record in records if answers[_lookup_for(record)] is None),
        dmarc_policies={
            record: policies
            for record in records
            if record.kind == Kind.DMARC and (policies := _dmarc_policies(answers[_lookup_for(record)] or []))
        },
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
        return b"".join(rdata.strings).decode("utf-8", errors="replace").strip(" \t")
    if isinstance(rdata, CNAME):
        return _normalized_hostname(rdata.target.to_text())
    if isinstance(rdata, MX):
        return f"{rdata.preference} {_normalized_hostname(rdata.exchange.to_text())}"
    return None


def _normalized_hostname(hostname: str) -> str:
    return hostname.lower().rstrip(".")


def _is_published(record: EmailDomainStatusRecord, answers: list[str]) -> bool:
    if record.kind == Kind.DMARC:
        policies = _dmarc_policies(answers)
        return len(policies) == 1 and _policy_in_force(policies[0]) is not None
    answers = [answer.strip().strip('"') for answer in answers]
    match record.kind, record.type:
        case Kind.SPF | Kind.MAIL_FROM_SPF, _:
            # A second SPF record at the same name makes SPF fail for all mail from it (RFC 7208, 4.5).
            spf_records = [answer for answer in answers if _is_spf(answer)]
            return len(spf_records) == 1 and _spf_includes(spf_records[0], record.value)
        case _, RecordType.CNAME:
            return _normalized_hostname(record.value) in answers
        case _, RecordType.MX if record.priority is None:
            return any(answer.partition(" ")[2] == _normalized_hostname(record.value) for answer in answers)
        case _, RecordType.MX:
            return f"{record.priority} {_normalized_hostname(record.value)}" in answers
        case _:
            return record.value in answers


def _dmarc_policies(answers: list[str]) -> tuple[str, ...]:
    return tuple(answer for answer in answers if _DMARC_RECORD.match(answer))


def _policy_in_force(policy: str) -> str | None:
    specs = [spec.strip(" \t") for spec in policy.split(";")[1:]]
    if specs and not specs[-1]:
        specs.pop()
    fields = [spec.partition("=") for spec in specs]
    tags = [(name.strip(" \t").lower(), value.strip(" \t")) for name, _, value in fields]
    names = ["v", *(name for name, _ in tags)]
    if (
        not _DMARC_VERSION.match(policy)
        or not _DMARC_TEXT.fullmatch(policy)
        or not all(separator for _, separator, _ in fields)
        or not all(_DMARC_TAG_NAME.fullmatch(name) for name, _ in tags)
        or len(names) != len(set(names))
    ):
        return None
    shown = {
        name: value for name, value in tags if name in _DMARC_SHOWN_TAGS and _DMARC_SHOWN_TAGS[name].fullmatch(value)
    }
    if not tags or tags[0][0] != "p" or "p" not in shown or ("sp" in names and "sp" not in shown):
        return None
    return "; ".join(["v=DMARC1", *(f"{name}={value}" for name, value in shown.items())])


def _is_spf(answer: str) -> bool:
    version = answer.lower()
    return version == "v=spf1" or version.startswith("v=spf1 ")


# A domain can publish only one SPF record, so SES's mechanism usually sits next to another
# sender's. The record counts as published when it carries every include the expected one does.
def _spf_includes(published: str, expected: str) -> bool:
    expected_includes = {term for term in expected.lower().split() if term.startswith("include:")}
    return expected_includes.issubset(published.lower().split())
