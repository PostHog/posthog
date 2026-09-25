"""What a subject's matching rules mean for one surface."""

from datetime import datetime

from ..facade.enums import Surface
from .matching import RuleIndex, candidates, rule_matches
from .rules import SnapshotRule
from .subjects import Subject

SCOPE_SURFACES: dict[str, frozenset[Surface]] = {
    "all_access": frozenset({Surface.SIGNUP, Surface.APP, Surface.AI_GATEWAY}),
    "signup": frozenset({Surface.SIGNUP}),
    "ai_gateway": frozenset({Surface.AI_GATEWAY}),
    "email_code": frozenset({Surface.EMAIL_CODE}),
}

# The effect a rule needs to decide each surface.
SURFACE_EFFECT: dict[Surface, str] = {
    Surface.SIGNUP: "block",
    Surface.APP: "block",
    Surface.AI_GATEWAY: "block",
    Surface.EMAIL_CODE: "exempt",
}

PROTECTED_DOMAIN = "posthog.com"


def is_protected_domain(domain: str | None) -> bool:
    return domain is not None and (domain == PROTECTED_DOMAIN or domain.endswith(f".{PROTECTED_DOMAIN}"))


def _is_active(rule: SnapshotRule, now: datetime) -> bool:
    return rule.expires_at is None or rule.expires_at > now


def deciding_rule(index: RuleIndex, subject: Subject, surface: Surface, now: datetime) -> SnapshotRule | None:
    """The oldest active rule that decides this surface, or None when the subject is allowed."""
    effect = SURFACE_EFFECT[surface]
    # A rule written before the hub's save-time check still never blocks a posthog.com
    # account. Exemptions still apply to one.
    if effect == "block" and is_protected_domain(subject.domain):
        return None
    for rule in candidates(index, subject):
        if (
            rule.effect == effect
            and surface in SCOPE_SURFACES.get(rule.scope, frozenset())
            and _is_active(rule, now)
            and rule_matches(rule, subject)
        ):
            return rule
    return None
