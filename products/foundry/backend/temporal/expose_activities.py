"""Temporal activities backing the foundry-expose-bet workflow: setting a flag's
rollout percentage (through the feature-flags facade — never the FeatureFlag model
directly, see ``logic/exposure.py``'s module docstring) and evaluating guardrails
between ramp steps (reusing ``logic/scout.py``, shared with the periodic scout sweep).
"""

from __future__ import annotations

from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify


@dataclass
class SetFlagRolloutInput:
    team_id: int
    flag_id: int
    rollout_pct: float
    ensure_active: bool = False


@activity.defn
@asyncify
def set_flag_rollout_activity(input: SetFlagRolloutInput) -> None:
    from products.feature_flags.backend.facade import api as feature_flags_api  # noqa: PLC0415

    feature_flags_api.set_rollout_percentage(
        input.team_id, input.flag_id, input.rollout_pct, ensure_active=input.ensure_active, user=None
    )


@dataclass
class EvaluateGuardrailsInput:
    bet_id: str
    team_id: int


@dataclass
class GuardrailBreachOutput:
    name: str
    detail: str


@activity.defn
@asyncify
def evaluate_guardrails_activity(input: EvaluateGuardrailsInput) -> GuardrailBreachOutput | None:
    from ..logic import scout  # noqa: PLC0415
    from ..models import Bet  # noqa: PLC0415

    bet = Bet.objects.for_team(input.team_id).get(id=input.bet_id)
    for evaluation in scout.evaluate_guardrails(bet):
        if evaluation.parameterized and evaluation.breached:
            return GuardrailBreachOutput(name=evaluation.name, detail=evaluation.detail)
    return None
