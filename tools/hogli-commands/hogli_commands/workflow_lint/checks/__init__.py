"""Registry of workflow lint checks.

To add a new rule:

1. Add a new module here that defines a ``WorkflowCheck`` subclass.
2. Import the class below and append an instance to ``CHECKS``.

Order matters only for output stability — rules with a lower-numbered id show
up first.
"""

from __future__ import annotations

from ..check import WorkflowCheck
from .dorny_negation import DornyNegationCheck
from .job_timeouts import JobTimeoutsCheck
from .pr_concurrency import PrConcurrencyCheck
from .semgrep_services_coverage import SemgrepServicesCoverageCheck

CHECKS: list[WorkflowCheck] = [
    JobTimeoutsCheck(),
    PrConcurrencyCheck(),
    DornyNegationCheck(),
    SemgrepServicesCoverageCheck(),
]


def _check_aliases(check: WorkflowCheck) -> tuple[str, str]:
    """Lookup keys for a check: the full id and its ``WF###`` prefix."""
    return check.id.lower(), check.id.partition("-")[0].lower()


def _build_lookup(checks: list[WorkflowCheck]) -> dict[str, WorkflowCheck]:
    """Build the alias→check map and fail loudly on duplicate ids or prefixes."""
    lookup: dict[str, WorkflowCheck] = {}
    for check in checks:
        for alias in _check_aliases(check):
            existing = lookup.get(alias)
            if existing is not None and existing is not check:
                raise ValueError(
                    f"workflow check alias '{alias}' is registered by both "
                    f"{existing.id!r} and {check.id!r} — pick distinct WF### prefixes"
                )
            lookup[alias] = check
    return lookup


_LOOKUP: dict[str, WorkflowCheck] = _build_lookup(CHECKS)


def get_check(check_id: str) -> WorkflowCheck | None:
    """Resolve a check by full id or by its ``WF###`` prefix (case-insensitive)."""
    return _LOOKUP.get(check_id.strip().lower())


__all__ = ["CHECKS", "get_check"]
