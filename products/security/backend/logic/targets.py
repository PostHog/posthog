"""How each kind of rule target is written, stored and matched.

A target type is one entry in TARGETS. Adding a type is that entry plus its
TargetType value: the form, the admin, the lookup and the decision logic all read
from here.
"""

import re
import uuid
import ipaddress
from collections.abc import Callable
from typing import Literal

from posthog.dataclasses import frozen

from ..facade.enums import Scope, TargetType

# Gmail ignores dots in the local part, so one mailbox has many spellings.
DOT_INSENSITIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


class InvalidTarget(ValueError):
    """The value cannot be stored as this target type. The message is shown to the admin."""


@frozen
class Subject:
    """Who or what is being checked. A rule can only match a field that is set."""

    email: str | None = None
    domain: str | None = None
    user_uuid: str | None = None
    organization_ids: frozenset[str] = frozenset()
    team_ids: frozenset[int] = frozenset()
    ip: str | None = None

    @classmethod
    def for_account(
        cls,
        *,
        email: str | None,
        user_uuid: str | None = None,
        organization_ids: frozenset[str] = frozenset(),
        team_ids: frozenset[int] = frozenset(),
        ip: str | None = None,
    ) -> "Subject":
        address = (email or "").strip().lower() or None
        domain = (address.rpartition("@")[2] or None) if address else None
        return cls(
            email=address,
            domain=domain,
            user_uuid=user_uuid,
            organization_ids=organization_ids,
            team_ids=team_ids,
            ip=ip,
        )


def fold_email_root(address: str) -> str:
    """The mailbox an address delivers to: the +suffix dropped, and Gmail's dots removed."""
    local, at, domain = address.strip().lower().rpartition("@")
    if not at or not local or not domain:
        raise InvalidTarget("Enter a full email address, such as name@example.com.")
    root_local = local.split("+", 1)[0]
    if not root_local:
        raise InvalidTarget("The part before the @ is empty once the +suffix is removed.")
    if domain in DOT_INSENSITIVE_DOMAINS:
        return f"{root_local.replace('.', '')}@gmail.com"
    return f"{root_local}@{domain}"


def _normalize_email(value: str) -> str:
    address = value.strip().lower()
    local, at, domain = address.rpartition("@")
    if not at or not local or not _DOMAIN_RE.match(domain):
        raise InvalidTarget("Enter a full email address, such as name@example.com.")
    return address


def _normalize_email_root(value: str) -> str:
    # Accepts any alias of the mailbox and stores the folded root, so an admin can
    # paste the address straight from an abuse report.
    return fold_email_root(_normalize_email(value))


def _normalize_domain(value: str) -> str:
    domain = value.strip().lower().removeprefix("@")
    if not _DOMAIN_RE.match(domain):
        raise InvalidTarget("Enter a domain such as example.com, without a scheme or path.")
    return domain


def _normalize_uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        raise InvalidTarget("Enter a UUID, such as 0190c7c0-1c2b-7d3e-9f4a-5b6c7d8e9f01.")


def _normalize_team_id(value: str) -> str:
    stripped = value.strip()
    if not stripped.isdigit() or int(stripped) < 1:
        raise InvalidTarget("Enter a numeric project ID.")
    return str(int(stripped))


def _normalize_ip(value: str) -> str:
    try:
        # strict=False accepts a host address inside a range and stores the range.
        return str(ipaddress.ip_network(value.strip(), strict=False))
    except ValueError:
        raise InvalidTarget("Enter an IP address or a CIDR range, such as 203.0.113.0/24.")


def _match_user_uuid(value: str, subject: Subject) -> bool:
    return subject.user_uuid == value


def _match_email(value: str, subject: Subject) -> bool:
    return subject.email == value


def _match_email_root(value: str, subject: Subject) -> bool:
    if subject.email is None:
        return False
    try:
        return fold_email_root(subject.email) == value
    except InvalidTarget:
        return False


def _match_email_domain(value: str, subject: Subject) -> bool:
    # A domain rule also covers its subdomains, because a catch-all subdomain costs an
    # abuser nothing to rotate.
    domain = subject.domain
    return domain is not None and (domain == value or domain.endswith(f".{value}"))


def _match_organization_id(value: str, subject: Subject) -> bool:
    return value in subject.organization_ids


def _match_team_id(value: str, subject: Subject) -> bool:
    return int(value) in subject.team_ids


def _match_ip(value: str, subject: Subject) -> bool:
    if subject.ip is None:
        return False
    try:
        # Containment across IP versions is False rather than an error.
        return ipaddress.ip_address(subject.ip) in ipaddress.ip_network(value)
    except ValueError:
        return False


_ALL_SCOPES = frozenset({Scope.ALL_ACCESS, Scope.SIGNUP, Scope.AI_GATEWAY})


@frozen
class TargetSpec:
    label: str
    # "account" targets name an identity, so matched users can be found in the database.
    # "network" targets name where a request comes from, which no account records.
    family: Literal["account", "network"]
    scopes: frozenset[Scope]
    normalize: Callable[[str], str]
    matches: Callable[[str, Subject], bool]


TARGETS: dict[TargetType, TargetSpec] = {
    TargetType.USER_UUID: TargetSpec(
        label="User",
        family="account",
        # A signup has no user yet, so a signup scope could never match.
        scopes=frozenset({Scope.ALL_ACCESS, Scope.AI_GATEWAY}),
        normalize=_normalize_uuid,
        matches=_match_user_uuid,
    ),
    TargetType.EMAIL: TargetSpec(
        label="Email",
        family="account",
        scopes=_ALL_SCOPES,
        normalize=_normalize_email,
        matches=_match_email,
    ),
    TargetType.EMAIL_ROOT: TargetSpec(
        label="Email root",
        family="account",
        scopes=_ALL_SCOPES,
        normalize=_normalize_email_root,
        matches=_match_email_root,
    ),
    TargetType.EMAIL_DOMAIN: TargetSpec(
        label="Email domain",
        family="account",
        scopes=_ALL_SCOPES,
        normalize=_normalize_domain,
        matches=_match_email_domain,
    ),
    TargetType.ORGANIZATION_ID: TargetSpec(
        label="Organization",
        family="account",
        # All access for an organization would have to refuse members who also belong
        # to other organizations, so organization rules stay on the gateway.
        scopes=frozenset({Scope.AI_GATEWAY}),
        normalize=_normalize_uuid,
        matches=_match_organization_id,
    ),
    TargetType.TEAM_ID: TargetSpec(
        label="Project",
        family="account",
        scopes=frozenset({Scope.AI_GATEWAY}),
        normalize=_normalize_team_id,
        matches=_match_team_id,
    ),
    TargetType.IP: TargetSpec(
        label="IP address or range",
        family="network",
        scopes=_ALL_SCOPES,
        normalize=_normalize_ip,
        matches=_match_ip,
    ),
}
