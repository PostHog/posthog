import json
import hashlib
import ipaddress
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import DomainNameValidator

import idna

_domain_name_validator = DomainNameValidator(accept_idna=False)
_MODAL_UNSUPPORTED_HOSTS = {"localhost", "host.docker.internal"}
MAX_SANDBOX_ALLOWED_DOMAINS = 100


@dataclass(frozen=True, kw_only=True)
class InvalidDomain:
    index: int
    value: str
    reason: str


class NetworkPolicyValidationError(ValueError):
    def __init__(self, invalid_domains: Sequence[InvalidDomain]) -> None:
        self.invalid_domains = tuple(invalid_domains)
        positions = ", ".join(str(item.index + 1) for item in self.invalid_domains)
        super().__init__(f"Invalid allowed domain at position {positions}")


@dataclass(frozen=True, kw_only=True)
class EffectiveNetworkPolicy:
    requested_domains: tuple[str, ...]
    infrastructure_domains: tuple[str, ...]
    modal_domains: tuple[str, ...]
    agentsh_domains: tuple[str, ...]
    agentsh_debug_domains: tuple[str, ...]
    agentsh_debug_ports: tuple[int, ...]
    fingerprint: str


def normalize_domain(domain: str) -> str:
    normalized = domain.strip().lower()
    if not normalized:
        raise ValueError("Domain cannot be empty")

    wildcard = normalized.startswith("*.")
    hostname = normalized[2:] if wildcard else normalized
    if "*" in hostname:
        raise ValueError("Wildcards are only supported as the leftmost '*.' label")

    try:
        hostname = idna.encode(hostname, uts46=True).decode("ascii")
    except idna.IDNAError as error:
        raise ValueError("Domain is not valid IDNA") from error

    if hostname in _MODAL_UNSUPPORTED_HOSTS:
        raise ValueError("Local host aliases are not supported")
    if hostname.endswith("."):
        raise ValueError("Rooted domain names are not supported")

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("IP addresses are not supported")

    if "." not in hostname:
        raise ValueError("Domain must contain at least two labels")

    try:
        _domain_name_validator(hostname)
    except ValidationError as error:
        raise ValueError("Domain name is malformed") from error

    return f"*.{hostname}" if wildcard else hostname


def normalize_requested_domains(domains: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    invalid: list[InvalidDomain] = []
    for index, domain in enumerate(domains):
        try:
            value = normalize_domain(domain)
        except ValueError as error:
            invalid.append(InvalidDomain(index=index, value=domain, reason=str(error)))
            continue
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    if invalid:
        raise NetworkPolicyValidationError(invalid)
    return tuple(normalized)


def domain_pattern_matches(pattern: str, hostname: str) -> bool:
    normalized_hostname = hostname.rstrip(".").lower()
    if pattern.startswith("*."):
        base = pattern[2:]
        return normalized_hostname == base or normalized_hostname.endswith(f".{base}")
    return normalized_hostname == pattern


def _deduplicate(domains: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(domains))


def _collapse_modal_domains(domains: Sequence[str]) -> tuple[str, ...]:
    wildcard_bases = {domain[2:] for domain in domains if domain.startswith("*.")}
    result: list[str] = []
    seen: set[str] = set()

    def is_covered_by_parent_wildcard(base: str) -> bool:
        _, separator, parent = base.partition(".")
        while separator:
            if parent in wildcard_bases:
                return True
            _, separator, parent = parent.partition(".")
        return False

    for domain in domains:
        base = domain[2:] if domain.startswith("*.") else domain
        covered = is_covered_by_parent_wildcard(base)
        if not domain.startswith("*."):
            covered = covered or base in wildcard_bases
        if not covered and domain not in seen:
            result.append(domain)
            seen.add(domain)
    return tuple(result)


def _expand_agentsh_wildcard_apex(domains: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for domain in domains:
        if domain not in seen:
            result.append(domain)
            seen.add(domain)
        if domain.startswith("*.") and domain[2:] not in seen:
            apex = domain[2:]
            result.append(apex)
            seen.add(apex)
    return tuple(result)


def compile_network_policy(
    requested_domains: Sequence[str],
    *,
    infrastructure_domains: Sequence[str],
    debug_domains: Sequence[str] = (),
    debug_ports: Sequence[int] = (),
) -> EffectiveNetworkPolicy:
    requested = normalize_requested_domains(requested_domains)
    infrastructure = normalize_requested_domains(infrastructure_domains)
    external_domains = _deduplicate((*requested, *infrastructure))

    modal_debug_domains: list[str] = []
    seen_modal_debug_domains: set[str] = set()
    for domain in debug_domains:
        try:
            normalized = normalize_domain(domain)
        except ValueError:
            continue
        if normalized not in seen_modal_debug_domains:
            modal_debug_domains.append(normalized)
            seen_modal_debug_domains.add(normalized)

    modal_domains = _collapse_modal_domains((*external_domains, *modal_debug_domains))
    agentsh_domains = _expand_agentsh_wildcard_apex(external_domains)
    normalized_debug_ports = tuple(dict.fromkeys(int(port) for port in debug_ports))
    fingerprint_payload = {
        "agentsh_debug_domains": list(debug_domains),
        "agentsh_debug_ports": normalized_debug_ports,
        "agentsh_domains": agentsh_domains,
        "modal_domains": modal_domains,
        "version": 1,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return EffectiveNetworkPolicy(
        requested_domains=requested,
        infrastructure_domains=infrastructure,
        modal_domains=modal_domains,
        agentsh_domains=agentsh_domains,
        agentsh_debug_domains=tuple(debug_domains),
        agentsh_debug_ports=normalized_debug_ports,
        fingerprint=fingerprint,
    )
