"""
Facade for ml_inference.

The ONLY module other products are allowed to import. Accepts and returns the frozen contracts.
"""

from __future__ import annotations

from ..logic import decisions
from . import contracts


def decisions_enabled(team_id: int) -> bool:
    return decisions.decisions_enabled(team_id)


def decide(request: contracts.DecisionRequest) -> contracts.DecisionResult:
    """Ask the model for an enrolled team; raises DecisionsDisabledError otherwise."""
    if not decisions.decisions_enabled(request.team_id):
        raise contracts.DecisionsDisabledError(request.team_id)
    return decisions.decide(request)


def decide_unchecked(request: contracts.DecisionRequest) -> contracts.DecisionResult:
    """Ask the model regardless of enrollment. Operator tooling only; product callers use decide."""
    return decisions.decide(request)
