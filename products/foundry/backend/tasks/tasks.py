"""
Celery tasks for foundry.

foundry_attempt_gate_task drives the automatic ReviewHog gate: triggered by
logic/gate.py on run.finished/artifact.ready while building, it self-reschedules
until the review turn completes (or times out), then always resolves to a
gate.result BetEvent — mapped violations, or {skipped: true, reason}.
"""

from __future__ import annotations

from celery import shared_task

from ..facade import api as foundry_api
from ..facade.enums import BetEventKind, BetState

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
