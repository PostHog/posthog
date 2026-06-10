"""Severity scoring — pure, derived from the *researched* cutoff date (not a seeded table).

Severity is a function of how soon the cited removal date is. Unknown date ⇒ low (P3): we won't
manufacture urgency we can't cite.
"""

from __future__ import annotations

from datetime import date

from products.signals.backend.api_deprecation.schema import VALID_SEVERITIES, ResearchedDeprecation, Severity

_SEVERITY_RANK = {sev: rank for rank, sev in enumerate(VALID_SEVERITIES)}


def score_severity(cutoff_date: date | None, today: date) -> Severity:
    """Map a cited cutoff date to a P0..P3 severity. No date ⇒ P3 (no manufactured urgency)."""
    if cutoff_date is None:
        return "P3"
    days = (cutoff_date - today).days
    if days <= 30:  # past or imminent
        return "P0"
    if days <= 90:
        return "P1"
    if days <= 180:
        return "P2"
    return "P3"


def severity_rank(severity: Severity) -> int:
    return _SEVERITY_RANK[severity]


def select_most_urgent(
    researched: list[ResearchedDeprecation],
    today: date,
) -> list[ResearchedDeprecation]:
    """Return deprecated findings ordered most-urgent first (by severity, then soonest cutoff)."""
    deprecated = [r for r in researched if r.is_deprecated]
    return sorted(
        deprecated,
        key=lambda r: (severity_rank(score_severity(r.cutoff_date, today)), r.cutoff_date or date.max),
    )
