"""Which snapshot rules can match a subject, and whether one does.

Every target type except IP ranges is an exact lookup, so a decision stays fast with
thousands of rules. Domain rules are looked up once per suffix of the subject's domain.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping

from posthog.dataclasses import frozen

from .rules import SnapshotRule
from .subjects import Subject

_EXACT_TYPES = frozenset({"user_uuid", "email", "email_root", "email_domain", "organization_id", "everyone"})


def _match_ip(rule: SnapshotRule, subject: Subject) -> bool:
    if rule.network is None or subject.ip is None:
        return False
    # Containment across IP versions is False, not an error.
    if subject.ip in rule.network:
        return True
    mapped = getattr(subject.ip, "ipv4_mapped", None)
    return mapped is not None and mapped in rule.network


def _match_domain(rule: SnapshotRule, subject: Subject) -> bool:
    # A domain rule also covers its subdomains; a shared suffix is not a subdomain.
    domain = subject.domain
    return domain is not None and (domain == rule.target_value or domain.endswith(f".{rule.target_value}"))


_MATCHERS: dict[str, Callable[[SnapshotRule, Subject], bool]] = {
    "user_uuid": lambda rule, subject: subject.user_uuid == rule.target_value,
    "email": lambda rule, subject: subject.email == rule.target_value,
    "email_root": lambda rule, subject: subject.email_root == rule.target_value,
    "email_domain": _match_domain,
    "organization_id": lambda rule, subject: rule.target_value in subject.organization_ids,
    "ip": _match_ip,
    "everyone": lambda rule, subject: True,
}


def rule_matches(rule: SnapshotRule, subject: Subject) -> bool:
    # A type from another release matches nothing rather than failing every check.
    matcher = _MATCHERS.get(rule.target_type)
    return matcher is not None and matcher(rule, subject)


@frozen
class RuleIndex:
    exact: Mapping[tuple[str, str], tuple[SnapshotRule, ...]]
    networks: tuple[SnapshotRule, ...]


EMPTY_INDEX = RuleIndex(exact={}, networks=())


def build_index(rules: Iterable[SnapshotRule]) -> RuleIndex:
    exact: defaultdict[tuple[str, str], list[SnapshotRule]] = defaultdict(list)
    networks: list[SnapshotRule] = []
    for rule in rules:
        if rule.target_type == "ip":
            networks.append(rule)
        elif rule.target_type in _EXACT_TYPES:
            exact[(rule.target_type, rule.target_value)].append(rule)
    return RuleIndex(exact={key: tuple(value) for key, value in exact.items()}, networks=tuple(networks))


def _domain_suffixes(domain: str | None) -> list[str]:
    if not domain:
        return []
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(len(labels))]


def candidates(index: RuleIndex, subject: Subject) -> list[SnapshotRule]:
    keys: list[tuple[str, str]] = [("everyone", "")]
    if subject.email:
        keys.append(("email", subject.email))
    if subject.email_root:
        keys.append(("email_root", subject.email_root))
    if subject.user_uuid:
        keys.append(("user_uuid", subject.user_uuid))
    keys.extend(("organization_id", org) for org in subject.organization_ids)
    keys.extend(("email_domain", suffix) for suffix in _domain_suffixes(subject.domain))

    found: dict[str, SnapshotRule] = {}
    for key in keys:
        for rule in index.exact.get(key, ()):
            found[rule.id] = rule
    if subject.ip is not None:
        for rule in index.networks:
            found[rule.id] = rule
    return sorted(found.values(), key=lambda rule: rule.id)
