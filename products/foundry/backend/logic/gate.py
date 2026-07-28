"""Automatic gauntlet hook: on run.finished / artifact.ready while building, kick off the
gate engine.

Uniform for both execution modes — the managed Temporal workflow and external orchestrators
both just record run.finished/artifact.ready via ``apply_event``, and this module decides
whether to start an automatic gate run. It always resolves to a gate.result event eventually
(a mapped check breakdown, or a graceful ``{skipped: true, reason}`` note if nothing was
configured to run); manual gate.result via the events API keeps working unconditionally,
gated bet or not.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS

from ..models import Bet

logger = logging.getLogger(__name__)

FOUNDRY_REVIEWHOG_GATE_FLAG = "foundry-reviewhog-gate"


def reviewhog_gate_enabled(bet: Bet) -> bool:
    """Match in-app flag evaluation: project/org groups, no particular user.

    Despite the name (kept for continuity with iteration 2 — this is the same flag,
    reused), this now gates *any* automatic gauntlet run, not just a bare ReviewHog poll:
    with the flag off, a bet's gate_config never runs itself and only a manual
    ``gate.result`` via the events API advances it past building.
    """
    if FOUNDRY_REVIEWHOG_GATE_FLAG in _FORCE_ENABLED_FLAGS:
        return True
    team = bet.team
    organization_id = str(team.organization_id)
    project_id = str(team.id)
    return bool(
        posthoganalytics.feature_enabled(
            FOUNDRY_REVIEWHOG_GATE_FLAG,
            str(team.uuid),
            groups={"organization": organization_id, "project": project_id},
            group_properties={"organization": {"id": organization_id}, "project": {"id": project_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    )


def maybe_schedule_gate(bet: Bet, artifact: dict[str, Any]) -> None:
    """Enqueue an automatic gauntlet run after commit, if the flag allows it and the bet
    has any checks configured.

    A no-op (not an error) in either case — the bet just waits for a manual ``gate.result``
    via the events API, exactly as if this hook didn't exist.
    """
    if not reviewhog_gate_enabled(bet):
        return
    if not (bet.gate_config or {}).get("checks"):
        return

    bet_id = str(bet.id)
    team_id = bet.team_id
    bet_slug = bet.slug
    created_by_id = bet.created_by_id
    gate_config = bet.gate_config
    transaction.on_commit(
        lambda: _start_gate_workflow_or_degrade(bet_id, team_id, bet_slug, created_by_id, gate_config, artifact)
    )


def _start_gate_workflow_or_degrade(
    bet_id: str,
    team_id: int,
    bet_slug: str,
    created_by_id: int | None,
    gate_config: dict[str, Any],
    artifact: dict[str, Any],
) -> None:
    """Start the foundry-run-gate workflow; degrade to the iteration-2 ReviewHog-only
    Celery path if Temporal/sandboxes are unavailable, so a gate.result still lands rather
    than leaving the bet stuck in building."""
    # Deferred: the workflow module (and the temporalio workflow sandbox it drags in) stays
    # off the Celery task-dispatch import path until a gate actually needs to run.
    from ..temporal.gate_client import execute_foundry_run_gate_workflow  # noqa: PLC0415

    try:
        execute_foundry_run_gate_workflow(
            bet_id=bet_id,
            team_id=team_id,
            bet_slug=bet_slug,
            created_by_id=created_by_id,
            gate_config=gate_config,
            artifact=artifact,
        )
    except Exception:
        logger.exception(
            "foundry: could not start foundry-run-gate workflow, degrading to the ReviewHog-only gate",
            extra={"bet_id": bet_id},
        )
        from ..tasks.tasks import foundry_attempt_gate_task  # noqa: PLC0415 — breaks a logic<->tasks import cycle

        foundry_attempt_gate_task.delay(bet_id, team_id, artifact.get("pr_url"))
