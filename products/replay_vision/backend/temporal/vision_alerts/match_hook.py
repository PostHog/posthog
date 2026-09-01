"""Observation-completion hook for match-kind vision alerts.

Called from inside the observation success transaction, after the conditional status
UPDATE has actually transitioned the row (the exactly-once guard). Inserts one
VisionAlertMatch outbox row per matching enabled match alert; the alert-check workflow
drains undelivered rows into one bundled notification per alert per tick.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception

from products.replay_vision.backend.models.vision_alert import (
    VisionAlertConfiguration,
    VisionAlertKind,
    VisionAlertMatch,
    selection_has_predicate,
)

logger = structlog.get_logger(__name__)


def record_alert_matches_guarded(
    *,
    observation_id: UUID,
    team_id: int,
    scanner_id: UUID,
    model_output: dict[str, Any],
) -> None:
    """Match the observation against enabled match alerts inside a savepoint.

    A hook failure must not roll back the observation's status transition, so the
    insert runs in a nested atomic block and any exception is swallowed after logging:
    a lost match beats a broken scan.
    """
    try:
        with transaction.atomic():
            _record_alert_matches(
                observation_id=observation_id,
                team_id=team_id,
                scanner_id=scanner_id,
                model_output=model_output,
            )
    except Exception as e:
        capture_exception(e, {"observation_id": str(observation_id), "phase": "vision_alert_match_hook"})
        logger.exception("vision_alert.match_hook_failed", observation_id=str(observation_id))


def selection_matches(model_output: dict[str, Any], selection: dict[str, Any]) -> bool:
    """Python mirror of `apply_observation_predicate` for one in-memory model output.

    Keeps the hot success path free of per-alert single-row queries. Semantics must
    stay aligned with the queryset version in vision_actions.synthesis.
    """
    verdicts = selection.get("verdict")
    if verdicts:
        if isinstance(verdicts, str):
            verdicts = [verdicts]
        if model_output.get("verdict") not in verdicts:
            return False

    tags = selection.get("tags")
    if tags:
        carried = set(model_output.get("tags") or []) | set(model_output.get("tags_freeform") or [])
        if not carried.intersection(tags):
            return False

    for key, opposite in (("min_score", False), ("max_score", True)):
        bound = selection.get(key)
        # Mirror apply_observation_predicate: non-numeric bounds (bool included) are ignored.
        if not isinstance(bound, int | float) or isinstance(bound, bool):
            continue
        score = model_output.get("score")
        if not isinstance(score, int | float) or isinstance(score, bool):
            return False
        if (score > bound) if opposite else (score < bound):
            return False

    return True


def _record_alert_matches(
    *,
    observation_id: UUID,
    team_id: int,
    scanner_id: UUID,
    model_output: dict[str, Any],
) -> int:
    alerts = list(
        VisionAlertConfiguration.all_teams.filter(
            team_id=team_id,
            scanner_id=scanner_id,
            kind=VisionAlertKind.MATCH,
            enabled=True,
        ).only("id", "selection")
    )
    if not alerts:
        return 0

    rows: list[VisionAlertMatch] = []
    for alert in alerts:
        selection = alert.selection or {}
        if selection_has_predicate(selection) and not selection_matches(model_output, selection):
            continue
        rows.append(
            VisionAlertMatch(
                alert_id=alert.id,
                observation_id=observation_id,
                team_id=team_id,
            )
        )

    if rows:
        # ignore_conflicts: the unique (alert, observation) constraint makes a
        # double insert structurally impossible even if the exactly-once guard slips.
        VisionAlertMatch.all_teams.bulk_create(rows, ignore_conflicts=True)
    return len(rows)
