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
    return decisions.decide(request)
