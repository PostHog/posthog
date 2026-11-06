"""Who or what a decision is about, normalized once per decision."""

import uuid
import ipaddress
import dataclasses
from collections.abc import Iterable

from posthog.dataclasses import frozen

# Gmail ignores dots in the local part, so one mailbox has many spellings.
DOT_INSENSITIVE_DOMAINS = frozenset({"gmail.com", "googlemail.com"})

# SMTP caps a deliverable address at 254 characters. Longer input is refused so the domain suffix expansion stays small.
MAX_ADDRESS_LENGTH = 254

LOOKALIKE_DOTS = "\u3002\uff0e\uff61\ufe52\u2024"
HIDDEN_CHARACTERS = "\u00ad\u200b\u200c\u200d\u2060\ufeff"
_FOLD_LOOKALIKES = str.maketrans(dict.fromkeys(LOOKALIKE_DOTS, ".") | dict.fromkeys(HIDDEN_CHARACTERS, None))


@frozen
class Subject:
    email: str | None = None
    email_root: str | None = None
    domain: str | None = None
    user_uuid: str | None = None
    organization_ids: frozenset[str] = frozenset()
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    lookalike: "Subject | None" = None


def fold_lookalikes(value: str) -> str:
    return value.translate(_FOLD_LOOKALIKES)


def fold_email_root(address: str) -> str | None:
    """The mailbox an address delivers to: the +suffix dropped, and Gmail's dots removed."""
    local, at, domain = address.strip().lower().rpartition("@")
    if not at or not local or not domain:
        return None
    root_local = local.split("+", 1)[0]
    if not root_local:
        return None
    if domain in DOT_INSENSITIVE_DOMAINS:
        return f"{root_local.replace('.', '')}@gmail.com"
    return f"{root_local}@{domain}"


def _canonical_uuid(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return None


def _parse_ip(value: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    if not value:
        return None
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def normalize_subject(
    *,
    email: str | None = None,
    domain: str | None = None,
    user_uuid: str | None = None,
    organization_ids: Iterable[str] = (),
    ip: str | None = None,
) -> Subject:
    address = (email or "").strip().lower() or None
    if address and len(address) > MAX_ADDRESS_LENGTH:
        address = None
    if address:
        subject_domain = address.rpartition("@")[2] or None
    else:
        subject_domain = (domain or "").strip().lower().removeprefix("@") or None
    if subject_domain and len(subject_domain) > MAX_ADDRESS_LENGTH:
        subject_domain = None
    subject = Subject(
        email=address,
        email_root=fold_email_root(address) if address else None,
        domain=subject_domain,
        user_uuid=_canonical_uuid(user_uuid),
        organization_ids=frozenset(filter(None, (_canonical_uuid(org) for org in organization_ids))),
        ip=_parse_ip(ip),
    )
    folded_address = fold_lookalikes(address) if address else None
    folded_domain = fold_lookalikes(subject_domain) if subject_domain else None
    if folded_address == address and folded_domain == subject_domain:
        return subject
    return dataclasses.replace(
        subject,
        lookalike=dataclasses.replace(
            subject,
            email=folded_address,
            email_root=fold_email_root(folded_address) if folded_address else None,
            domain=folded_domain or None,
        ),
    )
