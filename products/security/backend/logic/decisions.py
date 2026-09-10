"""Which rules match a subject, and what that means for each surface."""

from collections.abc import Iterable

from posthog.dataclasses import frozen

from ..facade.enums import Effect, Scope, Surface, TargetType
from ..models import SecurityRule
from .targets import TARGETS, Subject

SCOPE_SURFACES: dict[Scope, frozenset[Surface]] = {
    Scope.ALL_ACCESS: frozenset({Surface.SIGNUP, Surface.APP_ACCESS, Surface.AI_GATEWAY}),
    Scope.SIGNUP: frozenset({Surface.SIGNUP}),
    Scope.AI_GATEWAY: frozenset({Surface.AI_GATEWAY}),
}


@frozen
class SurfaceDecision:
    surface: Surface
    blocked: bool
    deciding_rule: SecurityRule | None


def matching_rules(subject: Subject, rules: Iterable[SecurityRule] | None = None) -> list[SecurityRule]:
    candidates = SecurityRule.objects.active().order_by("created_at") if rules is None else rules
    return [rule for rule in candidates if _matches(rule, subject)]


def decide(subject: Subject, rules: Iterable[SecurityRule] | None = None) -> list[SurfaceDecision]:
    blocks = [rule for rule in matching_rules(subject, rules) if rule.effect == Effect.BLOCK]
    decisions = []
    for surface in Surface:
        deciding_rule = next((rule for rule in blocks if surface in _surfaces(rule)), None)
        decisions.append(
            SurfaceDecision(surface=surface, blocked=deciding_rule is not None, deciding_rule=deciding_rule)
        )
    return decisions


def _matches(rule: SecurityRule, subject: Subject) -> bool:
    # A value this code no longer recognizes, from a rolled-back release, matches nothing
    # rather than failing every check.
    try:
        spec = TARGETS[TargetType(rule.target_type)]
    except ValueError:
        return False
    return spec.matches(rule.target_value, subject)


def _surfaces(rule: SecurityRule) -> frozenset[Surface]:
    try:
        return SCOPE_SURFACES[Scope(rule.scope)]
    except ValueError:
        return frozenset()
