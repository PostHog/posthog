"""ReviewHog gate hook: on run.finished / artifact.ready while building, attempt a gate.

Uniform for both execution modes — the managed Temporal workflow and external orchestrators
both just record run.finished/artifact.ready via ``apply_event``, and this module decides
whether to kick off an automatic gate. It always resolves to a gate.result event (mapped
violations, or ``{skipped: true, reason}``); manual gate.result via the events API keeps
working unconditionally, gated bet or not.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

import posthoganalytics

from posthog.permissions import _FORCE_ENABLED_FLAGS

from ..models import Bet

if TYPE_CHECKING:
    pass

FOUNDRY_REVIEWHOG_GATE_FLAG = "foundry-reviewhog-gate"


def reviewhog_gate_enabled(bet: Bet) -> bool:
    """Match in-app flag evaluation: project/org groups, no particular user."""
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


def maybe_schedule_gate(bet: Bet, pr_url: str | None) -> None:
    """Enqueue an automatic gate attempt after commit, if the flag allows it.

    A no-op (not an error) when the flag is off — the bet just waits for a manual
    ``gate.result`` via the events API, exactly as if this hook didn't exist.
    """
    if not reviewhog_gate_enabled(bet):
        return
    # Local import: tasks/tasks.py -> facade/api.py -> `from .. import logic` closes a cycle
    # back to this package; deferring keeps logic/__init__ import order irrelevant.
    from ..tasks.tasks import foundry_attempt_gate_task  # noqa: PLC0415 — breaks a logic<->tasks import cycle

    bet_id = str(bet.id)
    team_id = bet.team_id
    transaction.on_commit(lambda: foundry_attempt_gate_task.delay(bet_id, team_id, pr_url))
