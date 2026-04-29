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


def get_check(check_id: str) -> WorkflowCheck | None:
    return next((c for c in CHECKS if c.id == check_id), None)


__all__ = ["CHECKS", "get_check"]
