"""Clearbit fallback for the ICP score's est_revenue input.

A separate hog function projects Clearbit's own company lookup onto the signer's person
profile under `person.properties.clearbit.*`, independently of the Clay bridge and on its
own delay (median ~8s after signup, p99 ~3min). Pure extraction: no I/O — callers own the
person fetch and hand this module the resulting properties dict.
"""

import dataclasses
from typing import Any, Optional

# Clearbit reports revenue as a band string, not a number, but the formula's comparisons are
# strict (`1_000_000 < x < 50_000_001`) and need a number. Midpoints, never band lower bounds:
# a lower-bound representative sitting exactly on a boundary would silently miss the term it's
# meant to score. "$10B+" has no upper bound, so its representative is chosen past $10B rather
# than derived from one.
_REVENUE_BAND_MIDPOINTS: dict[str, float] = {
    "$0-$1M": 500_000.0,
    "$1M-$10M": 5_500_000.0,
    "$10M-$50M": 30_000_000.0,
    "$50M-$100M": 75_000_000.0,
    "$100M-$250M": 175_000_000.0,
    "$250M-$500M": 375_000_000.0,
    "$500M-$1B": 750_000_000.0,
    "$1B-$10B": 5_500_000_000.0,
    "$10B+": 15_000_000_000.0,
}


@dataclasses.dataclass(frozen=True)
class ClearbitInputs:
    """Clearbit-owned score inputs read off the signer's person profile. Empty when never written."""

    est_revenue: Optional[float] = None


def _get_dict(mapping: Any, key: str) -> dict[str, Any]:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if isinstance(value, dict) else {}


def clearbit_inputs_from_person_properties(properties: dict[str, Any]) -> ClearbitInputs:
    """Extract Clearbit's revenue band off the person's `clearbit.*` properties.

    The payload is a third-party API response stored verbatim, so every level is guarded rather
    than assumed present or well-typed — a missing key, a None, or a wrong-shaped value at any
    level degrades to the corresponding field staying None instead of raising. US-only in
    effect: the Clearbit hog function writes only to the US internal project, so elsewhere the
    `clearbit` block is simply absent and extraction degrades to empty the same way.
    """
    company = _get_dict(_get_dict(properties, "clearbit"), "company")
    band = _get_dict(company, "metrics").get("estimatedAnnualRevenue")
    return ClearbitInputs(est_revenue=_REVENUE_BAND_MIDPOINTS.get(band) if isinstance(band, str) else None)
