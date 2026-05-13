"""
Facade for githog.

This is the ONLY module other products are allowed to import.

Responsibilities:
- Accept frozen dataclasses as input parameters
- Call business logic (logic.py)
- Convert Django models to frozen dataclasses before returning
- Enforce transactions where needed
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
"""

from typing import TYPE_CHECKING

from ..logic.diff_scanner import extract_flag_keys
from ..logic.flag_reach import compute_intersection_reach, compute_per_flag_reach
from .contracts import PRImpactReport, PRImpactRequest

if TYPE_CHECKING:
    from posthog.models import Team


def compute_pr_impact(team: "Team", request: PRImpactRequest) -> PRImpactReport:
    """Score the user-facing impact of a PR diff.

    Returns the empirical intersection of users who have evaluated
    every referenced flag truthy in the lookback window, plus per-flag
    breakdowns and notes about confidence.
    """
    references = extract_flag_keys(request.diff_text)
    # Constants (FEATURE_FLAGS.X) cannot be resolved to string keys
    # statically, so they are surfaced as references but excluded from
    # the reach query — including them would either error (no such
    # flag key) or be misleading.
    queryable_keys = [r.key for r in references if not r.key.startswith("const:")]

    notes: list[str] = []
    unresolved_consts = [r.key for r in references if r.key.startswith("const:")]
    if unresolved_consts:
        notes.append(
            f"{len(unresolved_consts)} flag reference(s) use constants — "
            f"resolve them in code to get reach: {', '.join(unresolved_consts)}"
        )

    per_flag = compute_per_flag_reach(team, queryable_keys, request.lookback_days)
    no_data = [f.key for f in per_flag if not f.has_data]
    if no_data:
        notes.append(
            f"{len(no_data)} flag(s) have no recent evaluations — reach unknown, not zero: {', '.join(no_data)}"
        )

    intersection_users, intersection_sessions = compute_intersection_reach(team, queryable_keys, request.lookback_days)

    return PRImpactReport(
        flag_references=tuple(references),
        per_flag_reach=tuple(per_flag),
        intersection_users=intersection_users,
        intersection_sessions=intersection_sessions,
        lookback_days=request.lookback_days,
        notes=tuple(notes),
    )
