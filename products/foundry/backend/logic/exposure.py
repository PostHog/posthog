"""Automatic exposure-ramp hook: on the gated->exposed transition, kick off the
foundry-expose-bet Temporal workflow when the bet's exposure_plan requests it.

Mirrors ``gate.py``'s ``maybe_schedule_gate`` shape: a human/orchestrator still always
sends the first ``exposure.started`` event (grey-box unchanged — manual flag edits keep
working); this hook only decides whether Foundry should *then* drive the ramp itself.
No steps / ``auto_start`` false is a no-op, exactly as if this hook didn't exist. Unlike
the gate hook, there is no Celery-degrade path: this automation is additive convenience
on top of a bet that already works exposed-and-unramped, not a previously-working path
being replatformed onto Temporal — if Temporal is unavailable the bet simply sits
exposed for a human to ramp by hand.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from ..models import Bet

logger = logging.getLogger(__name__)


def maybe_schedule_exposure(bet: Bet) -> None:
    plan = bet.exposure_plan or {}
    steps = list(plan.get("steps") or [])
    if not steps or not plan.get("auto_start"):
        return
    if bet.feature_flag_id is None:
        logger.warning(
            "foundry: exposure_plan requests auto_start but bet has no feature_flag", extra={"bet_id": str(bet.id)}
        )
        return

    bet_id = str(bet.id)
    team_id = bet.team_id
    bet_slug = bet.slug
    flag_id = bet.feature_flag_id
    guardrails = list(bet.guardrails or [])
    transaction.on_commit(lambda: _start_exposure_workflow(bet_id, team_id, bet_slug, flag_id, guardrails, steps))


def _start_exposure_workflow(
    bet_id: str,
    team_id: int,
    bet_slug: str,
    flag_id: int,
    guardrails: list[dict[str, Any]],
    steps: list[dict[str, Any]],
) -> None:
    # Deferred: the workflow module (and the temporalio workflow sandbox it drags in)
    # stays off the Celery/web import path until a bet actually reaches exposed.
    from ..temporal.expose_client import execute_foundry_expose_bet_workflow  # noqa: PLC0415

    try:
        execute_foundry_expose_bet_workflow(
            bet_id=bet_id, team_id=team_id, bet_slug=bet_slug, flag_id=flag_id, guardrails=guardrails, steps=steps
        )
    except Exception:
        logger.exception("foundry: could not start foundry-expose-bet workflow", extra={"bet_id": bet_id})
