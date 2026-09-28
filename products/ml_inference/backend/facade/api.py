"""
Facade for ml_inference.

The ONLY module other products are allowed to import. Accepts and returns the frozen contracts.
"""

from __future__ import annotations

from ..logic import decisions
from . import contracts


def decisions_enabled(team_id: int) -> bool:
    return decisions.decisions_enabled(team_id)


def decisions_available() -> bool:
    """Whether a caller with its own rollout gate can use the configured decision service."""
    return decisions.decisions_available_here() and decisions.gateway_configured()


async def async_decide_when_available(
    request: contracts.DecisionRequest, *, timeout_seconds: float
) -> contracts.DecisionResult:
    """Ask with a total network deadline; the caller owns its rollout gate."""
    if not decisions.decisions_available_here():
        raise contracts.DecisionsDisabledError(request.team_id)
    return await decisions.async_decide(request, timeout_seconds=timeout_seconds)


def decide(request: contracts.DecisionRequest) -> contracts.DecisionResult:
    """Ask the model for an enrolled team; raises DecisionsDisabledError otherwise."""
    if not decisions.decisions_enabled(request.team_id):
        raise contracts.DecisionsDisabledError(request.team_id)
    return decisions.decide(request)


def decide_when_available(
    request: contracts.DecisionRequest, *, timeout_seconds: float | None = None
) -> contracts.DecisionResult:
    """Ask the model where the decision service is available; the caller owns its rollout gate."""
    if not decisions.decisions_available_here():
        raise contracts.DecisionsDisabledError(request.team_id)
    if timeout_seconds is None:
        return decisions.decide(request)
    return decisions.decide(request, timeout_seconds=timeout_seconds)


def decide_unchecked(
    request: contracts.DecisionRequest, *, timeout_seconds: float | None = None
) -> contracts.DecisionResult:
    """Ask the model when the caller owns its rollout gate."""
    if timeout_seconds is None:
        return decisions.decide(request)
    return decisions.decide(request, timeout_seconds=timeout_seconds)
