"""Checks a new rule must pass before it is saved. Each refusal is a message the admin can act on."""

import ipaddress

from disposable_email_domains import blocklist as disposable_email_domains
from free_email_domains import whitelist as free_email_domains

from posthog.dataclasses import frozen

from ..facade.enums import Effect, Scope, TargetType
from .targets import TARGETS

# Only blocks are enforced so far. An exemption or a limit saved now would look active
# in the admin while nothing honored it.
CREATABLE_EFFECTS = frozenset({Effect.BLOCK})

# Wider ranges reach carrier NAT, VPN egress and shared hosting, where one abuser shares
# addresses with many unrelated users. A /48 is one IPv6 site.
_MIN_IPV4_PREFIX = 16
_MIN_IPV6_PREFIX = 48

_SCOPE_LABELS = {
    Scope.ALL_ACCESS: "all access",
    Scope.SIGNUP: "signup",
    Scope.AI_GATEWAY: "the AI gateway",
}


@frozen
class RuleDraft:
    target_type: TargetType
    # Already normalized by the target's registry entry.
    target_value: str
    effect: Effect
    scope: Scope


def check_rule(draft: RuleDraft, *, requester_ip: str | None) -> list[str]:
    spec = TARGETS[draft.target_type]
    errors: list[str] = []

    if draft.effect not in CREATABLE_EFFECTS:
        errors.append("Only block rules can be created for now.")

    if draft.scope not in spec.scopes:
        allowed = " or ".join(sorted(_SCOPE_LABELS[scope] for scope in spec.scopes))
        errors.append(f"A {spec.label.lower()} rule can only apply to {allowed}.")

    if draft.target_type == TargetType.EMAIL_DOMAIN:
        errors.extend(_check_email_domain(draft.target_value))

    if draft.target_type == TargetType.IP:
        errors.extend(_check_ip_range(draft, requester_ip))

    return errors


def _check_email_domain(domain: str) -> list[str]:
    # A disposable provider can sit on both lists, and blocking it is the point.
    if domain in free_email_domains and domain not in disposable_email_domains:
        return [
            f"{domain} is a free email provider that many legitimate users rely on. "
            "Block an email root or an address instead."
        ]
    return []


def _check_ip_range(draft: RuleDraft, requester_ip: str | None) -> list[str]:
    network = ipaddress.ip_network(draft.target_value)
    errors: list[str] = []

    # A request can only come from a globally routable address once the proxy chain is
    # trusted. A private or reserved range here would match the infrastructure itself.
    if not network.is_global:
        errors.append(f"{network} is a private, reserved or documentation range. Enter a public address.")

    min_prefix = _MIN_IPV4_PREFIX if network.version == 4 else _MIN_IPV6_PREFIX
    if network.prefixlen < min_prefix:
        errors.append(f"{network} is wider than /{min_prefix}. Split it into narrower ranges.")

    # With no trusted address for the admin, enforcement cannot resolve one for them
    # either, so the rule cannot lock them out.
    if draft.scope == Scope.ALL_ACCESS and requester_ip is not None:
        try:
            if ipaddress.ip_address(requester_ip) in network:
                errors.append(
                    f"Your own address, {requester_ip}, is inside {network}. Saving it would lock you out of this page."
                )
        except ValueError:
            pass

    return errors
