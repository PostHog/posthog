"""
Celery tasks for foundry.

foundry_attempt_gate_task drives the automatic ReviewHog gate: triggered by
logic/gate.py on run.finished/artifact.ready while building, it self-reschedules
until the review turn completes (or times out), then always resolves to a
gate.result BetEvent — mapped violations, or {skipped: true, reason}.

foundry_scout_task is the beat-scheduled sweep (ADR-6): evaluate every exposed bet's
conclusion conditions (logic/scout.py) and record any new verdict.proposed events.
"""

from __future__ import annotations

import logging

from celery import shared_task

from ..facade import api as foundry_api
from ..facade.enums import BetEventKind, BetState
from ..logic import scout
from ..models import Bet

logger = logging.getLogger(__name__)

GATE_POLL_INTERVAL_SECONDS = 15
GATE_POLL_MAX_ATTEMPTS = 40  # ~10 minutes total


def _record_skip(team_id: int, bet_id: str, reason: str) -> None:
    foundry_api.record_event(team_id, bet_id, BetEventKind.GATE_RESULT, {"skipped": True, "reason": reason})


@shared_task(ignore_result=True)
def foundry_attempt_gate_task(bet_id: str, team_id: int, pr_url: str | None, attempt: int = 0) -> None:
    # Local import: review_hog's temporal client (imported transitively via its facade) pulls
    # in temporalio, which we'd rather not load on every foundry task-module import.
    from products.review_hog.backend.facade import api as review_hog_api  # noqa: PLC0415

    try:
        bet = foundry_api.get_bet(team_id, bet_id)
    except foundry_api.BetNotFound:
        return
    if bet.state != BetState.BUILDING:
        # Already gated, or moved on some other way (e.g. a manual gate.result raced this task).
        return
    if pr_url is None:
        _record_skip(team_id, bet_id, "No PR available to review for this run")
        return

    if attempt == 0:
        if bet.created_by_id is None:
            _record_skip(team_id, bet_id, "Bet has no creator to run the review as")
            return
        if not review_hog_api.is_review_available_for_team(team_id):
            _record_skip(team_id, bet_id, "ReviewHog is not enabled for this project")
            return
        trigger = review_hog_api.trigger_review(team_id=team_id, user_id=bet.created_by_id, pr_url=pr_url)
        if not trigger.started:
            _record_skip(team_id, bet_id, trigger.reason or "ReviewHog could not start a review")
            return

    status = review_hog_api.get_review_status(team_id=team_id, pr_url=pr_url)
    if status is None or status.in_progress:
        if attempt + 1 >= GATE_POLL_MAX_ATTEMPTS:
            _record_skip(team_id, bet_id, "Timed out waiting for the ReviewHog review")
            return
        foundry_attempt_gate_task.apply_async(
            args=[bet_id, team_id, pr_url, attempt + 1], countdown=GATE_POLL_INTERVAL_SECONDS
        )
        return

    violations = [{"code": v.code, "message": v.message, "severity": v.severity} for v in status.violations]
    blocking = [v for v in violations if v["severity"] == "must_fix"]
    foundry_api.record_event(
        team_id,
        bet_id,
        BetEventKind.GATE_RESULT,
        {"pass": not blocking, "violations": violations, "review_id": status.review_id},
    )


@shared_task(ignore_result=True)
def foundry_scout_task() -> None:
    """Sweep every exposed bet across every team and record any new verdict.proposed
    events. Cross-team by design — a beat task has no natural single-team context,
    unlike a request or a bet-scoped Temporal workflow (see CLAUDE.md's ``for_team``/
    ``unscoped()`` guidance: this is exactly the "genuinely cross-team" case).
    """
    for bet in Bet.objects.unscoped().filter(state=BetState.EXPOSED):
        try:
            for proposal in scout.propose_verdicts_for_bet(bet):
                foundry_api.record_event(
                    bet.team_id,
                    str(bet.id),
                    BetEventKind.VERDICT_PROPOSED,
                    {"recommendation": proposal.recommendation.value, "evidence": proposal.evidence},
                )
        except Exception:
            logger.exception("foundry-scout: sweep failed for bet", extra={"bet_id": str(bet.id)})
