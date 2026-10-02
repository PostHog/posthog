import time
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any, Literal

from unittest.mock import patch

import dns.name
import dns.query
import dns.rcode
import dns.rdata
import dns.rrset
import dns.message
import dns.resolver
import dns.exception
import dns.rdatatype
import dns.rdataclass
from dns.rdtypes.ANY.CNAME import CNAME
from dns.rdtypes.ANY.TXT import TXT

from posthog.dataclasses import frozen

from products.workflows.backend.test.fakes.faults import DnsFault, FaultInjector

PUBLIC_RESOLVER_ADDRESS = "8.8.8.8"
UNANSWERED_QUERY_SECONDS = 2.0
MAX_CNAME_CHAIN = 8
TTL = 300

RecordKey = tuple[dns.name.Name, dns.rdatatype.RdataType]
Lookup = Literal["zone", "public"]


def dns_operation(name: str, rdtype: str, *, at: Lookup | None = None) -> str:
    """Fault key for one lookup. `at` narrows it to the zone's own nameservers or to the public resolver."""
    lookup = f"{_relative_text(_absolute(name))}/{rdtype.upper()}"
    return f"dns:{at}:{lookup}" if at else f"dns:{lookup}"


@frozen
class _Zone:
    apex: dns.name.Name
    nameserver_addresses: tuple[str, ...]


@frozen
class _Resolution:
    rcode: dns.rcode.Rcode
    answer: tuple[dns.rrset.RRset, ...] = ()
    authority: tuple[dns.rrset.RRset, ...] = ()


class _ResolverClock:
    """Simulated time for dnspython, so an unanswered query uses up the resolver's lifetime without a real wait.
    Each thread keeps its own offset because the code under test runs lookups in parallel threads."""

    def __init__(self) -> None:
        self._offsets = threading.local()

    def time(self) -> float:
        return time.time() + self._offset()

    def sleep(self, seconds: float) -> None:
        self._offsets.value = self._offset() + seconds

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)

    def _offset(self) -> float:
        return getattr(self._offsets, "value", 0.0)


class FakeDnsZone:
    """The DNS seen through dnspython: zones with their own nameservers, and a public resolver that follows
    CNAME chains across zones. It answers at the network edge (`dns.query`), so the real `Resolver`,
    `zone_for_name` and answer parsing run unchanged."""

    def __init__(self, faults: FaultInjector) -> None:
        self._faults = faults
        self._zones: list[_Zone] = []
        self._records: dict[RecordKey, list[dns.rdata.Rdata]] = {}
        self._clock = _ResolverClock()
        self.queried_addresses: set[str] = set()

    @contextmanager
    def installed(self) -> Iterator["FakeDnsZone"]:
        with ExitStack() as stack:
            stack.enter_context(patch("dns.query.udp", self._answer_query))
            stack.enter_context(patch("dns.query.tcp", self._answer_query))
            stack.enter_context(patch.object(dns.resolver.Resolver, "read_resolv_conf", _use_public_resolver))
            stack.enter_context(patch.object(dns.resolver, "default_resolver", None))
            stack.enter_context(patch.object(dns.resolver, "time", self._clock))
            yield self

    def add_zone(self, apex: str, *, nameservers: dict[str, str] | None = None) -> None:
        """Adds a zone served by `nameservers` (hostname to address). Without nameservers the zone only
        answers through the public resolver."""
        nameservers = nameservers or {}
        self._zones.append(_Zone(apex=_absolute(apex), nameserver_addresses=tuple(nameservers.values())))
        self.publish(apex, "SOA", f"ns.{apex}. hostmaster.{apex}. 1 7200 3600 1209600 300")
        for hostname, address in nameservers.items():
            self.publish(apex, "NS", f"{hostname}.")
            if self._zone_containing(_absolute(hostname)) is None:
                self.add_zone(hostname.split(".", 1)[1])
            self.publish(hostname, "A", address)

    def publish(self, name: str, rdtype: str, *values: str) -> None:
        records = self._records.setdefault((_absolute(name), dns.rdatatype.from_text(rdtype)), [])
        records.extend(
            dns.rdata.from_text(dns.rdataclass.IN, rdtype, value, origin=dns.name.root, relativize=False)
            for value in values
        )

    def publish_txt(self, name: str, *values: str) -> None:
        self.publish(name, "TXT", *(f'"{value}"' for value in values))

    def unpublish(self, name: str, rdtype: str) -> None:
        self._records.pop((_absolute(name), dns.rdatatype.from_text(rdtype)), None)

    def answers(self, name: str, rdtype: str) -> list[dns.rdata.Rdata]:
        """What a public resolver returns for the lookup, following CNAMEs. Empty when nothing answers."""
        rdtype_value = dns.rdatatype.from_text(rdtype)
        resolution = self._resolve(_absolute(name), rdtype_value, within=None)
        return [rdata for rrset in resolution.answer if rrset.rdtype == rdtype_value for rdata in rrset]

    def txt_values(self, name: str) -> list[str]:
        return [_txt_value(rdata) for rdata in self.answers(name, "TXT") if isinstance(rdata, TXT)]

    def cname_target(self, name: str) -> str | None:
        targets = [rdata.target for rdata in self.answers(name, "CNAME") if isinstance(rdata, CNAME)]
        return _relative_text(targets[0]) if targets else None

    def _answer_query(
        self, query: dns.message.Message, where: str, timeout: float | None = None, *args: Any, **kwargs: Any
    ) -> dns.message.Message:
        self.queried_addresses.add(where)
        question = query.question[0]
        lookup = self._lookup_at(where)
        if lookup is None:
            self._time_out(timeout)
        name, rdtype = _relative_text(question.name), dns.rdatatype.to_text(question.rdtype)
        fault = self._faults.fault_for(
            dns_operation(name, rdtype, at="public" if lookup == "public" else "zone"), dns_operation(name, rdtype)
        )
        if fault == DnsFault.TIMEOUT:
            self._time_out(timeout)

        response = dns.message.make_response(query)
        if fault in (DnsFault.SERVFAIL, DnsFault.NXDOMAIN):
            response.set_rcode(dns.rcode.SERVFAIL if fault == DnsFault.SERVFAIL else dns.rcode.NXDOMAIN)
        else:
            resolution = self._resolve(question.name, question.rdtype, within=None if lookup == "public" else lookup)
            response.set_rcode(resolution.rcode)
            response.answer.extend(resolution.answer)
            response.authority.extend(resolution.authority)
        return dns.message.from_wire(response.to_wire())

    def _lookup_at(self, address: str) -> _Zone | Literal["public"] | None:
        if address == PUBLIC_RESOLVER_ADDRESS:
            return "public"
        return next((zone for zone in self._zones if address in zone.nameserver_addresses), None)

    def _time_out(self, timeout: float | None) -> None:
        self._clock.sleep(timeout or UNANSWERED_QUERY_SECONDS)
        raise dns.exception.Timeout(timeout=timeout)

    def _resolve(self, name: dns.name.Name, rdtype: dns.rdatatype.RdataType, *, within: _Zone | None) -> _Resolution:
        chain: list[dns.rrset.RRset] = []
        for _ in range(MAX_CNAME_CHAIN):
            zone = self._zone_containing(name)
            if zone is None or (within is not None and zone != within):
                if chain:
                    return _Resolution(rcode=dns.rcode.NOERROR, answer=tuple(chain))
                return _Resolution(rcode=dns.rcode.REFUSED if within else dns.rcode.NXDOMAIN)
            if records := self._records.get((name, rdtype)):
                return _Resolution(rcode=dns.rcode.NOERROR, answer=(*chain, _rrset(name, records)))
            alias = self._records.get((name, dns.rdatatype.CNAME))
            if not alias or rdtype == dns.rdatatype.CNAME or not isinstance(alias[0], CNAME):
                rcode = dns.rcode.NOERROR if self._name_exists(name) else dns.rcode.NXDOMAIN
                return _Resolution(rcode=rcode, answer=tuple(chain), authority=(self._soa(zone),))
            chain.append(_rrset(name, alias))
            name = alias[0].target
        return _Resolution(rcode=dns.rcode.SERVFAIL)

    def _zone_containing(self, name: dns.name.Name) -> _Zone | None:
        candidates = [zone for zone in self._zones if name.is_subdomain(zone.apex)]
        return max(candidates, key=lambda zone: len(zone.apex), default=None)

    def _name_exists(self, name: dns.name.Name) -> bool:
        return any(record_name.is_subdomain(name) for record_name, _ in self._records)

    def _soa(self, zone: _Zone) -> dns.rrset.RRset:
        return _rrset(zone.apex, self._records[(zone.apex, dns.rdatatype.SOA)])


def _use_public_resolver(resolver: dns.resolver.Resolver, _resolv_conf: object) -> None:
    resolver.nameservers = [PUBLIC_RESOLVER_ADDRESS]


def _rrset(name: dns.name.Name, records: list[dns.rdata.Rdata]) -> dns.rrset.RRset:
    return dns.rrset.from_rdata_list(name, TTL, records)


def _absolute(name: str) -> dns.name.Name:
    return dns.name.from_text(name.lower(), origin=dns.name.root)


def _relative_text(name: dns.name.Name) -> str:
    return name.to_text(omit_final_dot=True)


def _txt_value(rdata: TXT) -> str:
    return b"".join(rdata.strings).decode()
