"""Authoritative hard-cap enforcement for a user's self-set monthly budget.

The client-side budget brain (PostHog Code) is advisory UX. This is the
gateway's authoritative gate: when a user's self-set monthly cap is exceeded,
deny NEW generations. Two deliberate postures:

  - never kill an in-flight call — this only gates the start of a new request
  - FAIL OPEN, like quota_resolver: if spend can't be resolved (a Django
    hiccup), allow rather than block the user on our own error

Returns headers the client surfaces on the meter / to offer an override.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GuardDecision:
    allow: bool
    reason: str
    headers: dict[str, str]


def evaluate_request(
    monthly_budget_usd: float | None,
    scoped_spend_usd: float | None,
    *,
    override: bool = False,
) -> GuardDecision:
    if override:
        return GuardDecision(True, "explicit user override for this request", {"x-posthog-budget": "override"})
    if monthly_budget_usd is None or monthly_budget_usd <= 0:
        return GuardDecision(True, "no cap set", {})
    if scoped_spend_usd is None:
        return GuardDecision(True, "spend unresolved; failing open", {"x-posthog-budget": "unknown"})
    if scoped_spend_usd >= monthly_budget_usd:
        return GuardDecision(
            False,
            "monthly budget exceeded",
            {"x-posthog-budget": "exceeded", "x-posthog-budget-remaining-usd": "0.00"},
        )
    remaining = monthly_budget_usd - scoped_spend_usd
    if scoped_spend_usd / monthly_budget_usd >= 0.85:
        return GuardDecision(
            True,
            "approaching budget cap",
            {"x-posthog-budget": "warn", "x-posthog-budget-remaining-usd": f"{remaining:.2f}"},
        )
    return GuardDecision(
        True,
        "within budget",
        {"x-posthog-budget": "ok", "x-posthog-budget-remaining-usd": f"{remaining:.2f}"},
    )
