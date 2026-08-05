"""ICP scoring, transcribed from the Clay "ICP Scoring" formula column.

A faithful port, not a redesign: the formula, its weights, and its quirks are owned by
#team-demand-gen and revised separately. Scores are version-stamped so a later revision can
recompute historical orgs from the fetch archive under a new version without disturbing this
one. Behaviour is pinned to Clay's JS semantics — see `compute_icp_score`.

Deterministic and I/O-free: callers resolve the inputs (see bridge.py for the Clay-owned ones).
"""

import dataclasses
from typing import Optional

SCORE_VERSION = "clay-parity-1"

# Exempt from the -5 penalty. Matched case-sensitively against ISO alpha-2, as Clay does —
# `country_name_to_iso_code` already normalises provider names to this casing.
SCORED_COUNTRIES = frozenset(
    {
        "AU", "AT", "BE", "BR", "CA", "DK", "EE", "FI", "FR", "DE", "IS", "IE", "IL",
        "IT", "JP", "LV", "LT", "NL", "NZ", "NO", "PT", "SG", "KR", "ES", "SE", "CH",
        "GB", "US",
    }
)  # fmt: skip

ENGINEERING_LEANING_ROLES = frozenset({"engineering", "founder"})


@dataclasses.dataclass(frozen=True)
class IcpScoreInputs:
    """One org's scoring inputs. Every field is optional: absence is a scoring outcome, not an error."""

    employees: Optional[int] = None
    est_revenue: Optional[float] = None
    role: Optional[str] = None
    github_profile_url: Optional[str] = None
    company_type: Optional[str] = None
    founded_year: Optional[int] = None
    country: Optional[str] = None


def _in_band(value: Optional[float], low: int, high: int) -> bool:
    # Clay's `x > low && x < high` is false for a null x, where Python would raise.
    return value is not None and low < value < high


def _lowered(value: Optional[str]) -> Optional[str]:
    # Clay's `x?.toLowerCase()`, including "" staying falsy rather than matching a branch.
    return value.lower() if value else None


def compute_icp_score(inputs: IcpScoreInputs) -> int:
    """Score one org against the ICP, in the range -5..21 for whole-dollar revenue.

    Ports Clay's null semantics exactly: numeric branches score 0 on a missing value and role
    branches score 0 on a missing role, but a missing country lands outside the allowlist and
    so takes the -5 penalty. That penalty-on-missing is Clay's own behaviour as of its
    2026-06-25 fix, not an oversight here — country fill rate therefore moves scores directly.
    """
    role = _lowered(inputs.role)
    score = 0

    if _in_band(inputs.employees, 500, 1001):
        score += 3

    # Two independent terms, as in Clay. They cannot both fire for a whole-dollar revenue, but
    # a fractional one between 50000000 and 50000001 would score both — so don't fold them.
    if _in_band(inputs.est_revenue, 1_000_000, 50_000_001):
        score += 6
    if _in_band(inputs.est_revenue, 50_000_000, 100_000_001):
        score += 3

    if role in ENGINEERING_LEANING_ROLES:
        score += 6
    elif role == "product":
        score += 6 if inputs.github_profile_url else 3

    if _lowered(inputs.company_type) == "private":
        score += 3

    if inputs.founded_year is not None and inputs.founded_year > 2014:
        score += 3

    if inputs.country not in SCORED_COUNTRIES:
        score -= 5

    return score
