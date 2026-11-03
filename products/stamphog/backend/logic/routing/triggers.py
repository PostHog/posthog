"""What each routing trigger decides: a pull request event, a finished review, and the safety net.

`service.route_reviewers` does one routing run. These functions decide whether a run happens, and
with which claim, from the stored routing record and the live pull request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.db import router

import structlog

from posthog.dataclasses import frozen

from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict, RoutingMode
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.routing.service import (
    FULL_ROUTED_HEAD,
    PINNED_ROUTED_HEAD,
    STATUS_REQUESTED,
    STATUS_ROUTING,
    STATUS_WAITING,
    TRIGGER_SAFETY_NET,
    claim_routing,
    finish_comment,
    live_pr_skip_reason,
    route_reviewers,
    save_waiting,
    stored_routing,
    verdict_trigger,
)
from products.stamphog.backend.models import PullRequest, StamphogRepoConfig

logger = structlog.get_logger(__name__)


@frozen
class ReviewPath:
    """What routing needs from the review path. The task module owns these and passes them in."""

    upsert_pull_request: Callable[[StamphogRepoConfig, dict[str, Any]], PullRequest]
    # Whether the review path is expected to give a verdict on the live pull request.
    will_review: Callable[[StamphogRepoConfig, dict[str, Any]], bool]
    # Schedules the safety net for (repo_config, pr_number).
    schedule_safety_net: Callable[[StamphogRepoConfig, int], None]


def verdict_outcome(status: ReviewRunStatus, verdict: ReviewVerdict) -> str:
    """The routing outcome of a finished run: approved, refused, escalate, wait, gated or failed."""
    if status in (ReviewRunStatus.FAILED, ReviewRunStatus.GATED):
        return status.value
    return verdict.value


def _pull_request_row(repo_config: StamphogRepoConfig, pr_number: int) -> PullRequest:
    return (
        PullRequest.objects.for_team(repo_config.team_id)
        .using(router.db_for_write(PullRequest))
        .get(repo_config=repo_config, pr_number=pr_number)
    )


def _wait_for_verdict(
    repo_config: StamphogRepoConfig,
    pr_obj: PullRequest,
    review_path: ReviewPath,
    *,
    stored: dict[str, Any] | None,
    head_sha: str,
    trigger: str,
) -> None:
    # Scheduled before the record is saved, so a retry after a failed schedule schedules again.
    # A second safety net is harmless: only one task can claim the pull request.
    review_path.schedule_safety_net(repo_config, pr_obj.pr_number)
    save_waiting(pr_obj, expected=stored, head_sha=head_sha, trigger=trigger)


def route_on_pull_request_event(
    repo_config: StamphogRepoConfig, *, action: str, pr_number: int, review_path: ReviewPath
) -> None:
    """Route a pull request that opened or became ready, or make it wait for the verdict.

    The caller checks that ``action`` is a routing action.
    """
    if repo_config.routing_mode == RoutingMode.OFF:
        return
    mode = RoutingMode(repo_config.routing_mode)
    repo = repo_config.repository

    client = StamphogGitHubClient(repo_config.installation_id)
    # The live PR, not the payload: a draft toggle or a close can land between the two.
    pr = client.get_pr(repo, pr_number)
    skip_reason = live_pr_skip_reason(pr)
    if skip_reason is not None:
        logger.info("stamphog_reviewer_routing_skipped", repo=repo, pr_number=pr_number, reason=skip_reason)
        return

    head_sha = (pr.get("head") or {}).get("sha") or ""
    stored = stored_routing(repo_config, pr_number)
    if stored is not None and stored.get("head_sha") == head_sha:
        # ALWAYS routes once per head and action. FALLBACK routes once per head, whatever started it.
        if mode == RoutingMode.FALLBACK or stored.get("trigger") == action:
            if stored.get("status") == STATUS_REQUESTED:
                # A retry after the requests went out: finish the comment, request nobody again.
                finish_comment(client, _pull_request_row(repo_config, pr_number), stored)
            return

    if mode == RoutingMode.FALLBACK and stored is not None and stored.get(FULL_ROUTED_HEAD):
        return
    pr_obj = review_path.upsert_pull_request(repo_config, pr)
    if mode == RoutingMode.FALLBACK and review_path.will_review(repo_config, pr):
        _wait_for_verdict(repo_config, pr_obj, review_path, stored=stored, head_sha=head_sha, trigger=action)
        return
    route_reviewers(client, pr_obj, pr, trigger=action, mode=mode, previous=stored)


@frozen
class _FallbackState:
    """The FALLBACK view of one pull request: its config, its stored record and this task's own claim."""

    repo_config: StamphogRepoConfig
    stored: dict[str, Any] | None
    # The stored record, when this task wrote it in an earlier attempt.
    own_record: dict[str, Any] | None


def _fallback_state(team_id: int, repo_config_id: str, pr_number: int, task_id: str) -> _FallbackState | None:
    repo_config = (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(id=repo_config_id)
        .first()
    )
    if repo_config is None or repo_config.routing_mode != RoutingMode.FALLBACK:
        return None
    stored = stored_routing(repo_config, pr_number)
    own = stored is not None and bool(task_id) and stored.get("claimed_by") == task_id
    return _FallbackState(repo_config=repo_config, stored=stored, own_record=stored if own else None)


def _resume_own_record(client: StamphogGitHubClient, state: _FallbackState, pr_number: int) -> bool:
    """Finish what an earlier attempt of this task started. True when nothing is left to do."""
    record = state.own_record
    if record is None:
        return False
    if record.get("status") == STATUS_REQUESTED:
        # A retry after the requests went out: finish the comment, request nobody again.
        finish_comment(client, _pull_request_row(state.repo_config, pr_number), record)
        return True
    # A claim that never reached the requests routes again.
    return record.get("status") != STATUS_ROUTING


def _live_head(client: StamphogGitHubClient, repo_config: StamphogRepoConfig, pr_number: int) -> dict[str, Any] | None:
    """The live pull request, or None when it is closed or a draft."""
    pr = client.get_pr(repo_config.repository, pr_number)
    if live_pr_skip_reason(pr) is not None:
        return None
    return pr


def _claim_and_route(
    client: StamphogGitHubClient,
    state: _FallbackState,
    pr_obj: PullRequest,
    pr: dict[str, Any],
    *,
    head_sha: str,
    trigger: str,
    task_id: str,
    pinned_only: bool = False,
) -> None:
    claim = state.own_record or claim_routing(
        pr_obj, expected=state.stored, head_sha=head_sha, trigger=trigger, claimed_by=task_id
    )
    if claim is None:
        return
    route_reviewers(
        client, pr_obj, pr, trigger=trigger, mode=RoutingMode.FALLBACK, pinned_only=pinned_only, previous=claim
    )


def route_after_verdict(
    *,
    team_id: int,
    repo_config_id: str,
    pr_number: int,
    head_sha: str,
    outcome: str,
    task_id: str,
    review_path: ReviewPath,
) -> None:
    """Route a FALLBACK pull request once stamphog's review of ``head_sha`` ended.

    ``task_id`` is the Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    state = _fallback_state(team_id, repo_config_id, pr_number, task_id)
    if state is None:
        return
    repo_config = state.repo_config
    stored = state.stored
    client = StamphogGitHubClient(repo_config.installation_id)
    if _resume_own_record(client, state, pr_number):
        return
    if state.own_record is None:
        if stored is not None and stored.get(FULL_ROUTED_HEAD):
            return
        at_head = stored if stored is not None and stored.get("head_sha") == head_sha else None
        if at_head is not None and at_head.get("status") != STATUS_WAITING:
            # Another task already routed or claimed this head.
            return
        if outcome == ReviewVerdict.APPROVED and stored is not None and stored.get(PINNED_ROUTED_HEAD):
            return
        if outcome == ReviewVerdict.WAIT and at_head is not None:
            # Stamphog re-reviews after a WAIT. The safety net already covers this head.
            return

    pr = _live_head(client, repo_config, pr_number)
    if pr is None or (pr.get("head") or {}).get("sha") != head_sha:
        return
    pr_obj = review_path.upsert_pull_request(repo_config, pr)
    if outcome == ReviewVerdict.WAIT:
        _wait_for_verdict(
            repo_config, pr_obj, review_path, stored=stored, head_sha=head_sha, trigger=verdict_trigger(outcome)
        )
        return
    _claim_and_route(
        client,
        state,
        pr_obj,
        pr,
        head_sha=head_sha,
        trigger=verdict_trigger(outcome),
        task_id=task_id,
        pinned_only=outcome == ReviewVerdict.APPROVED,
    )


def route_on_safety_net(
    *, team_id: int, repo_config_id: str, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Route a FALLBACK pull request in full on its current head, unless it was already routed.

    ``task_id`` is the Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    state = _fallback_state(team_id, repo_config_id, pr_number, task_id)
    if state is None:
        return
    repo_config = state.repo_config
    stored = state.stored
    client = StamphogGitHubClient(repo_config.installation_id)
    if _resume_own_record(client, state, pr_number):
        return
    if state.own_record is None and stored is not None and stored.get(FULL_ROUTED_HEAD):
        return

    pr = _live_head(client, repo_config, pr_number)
    if pr is None:
        return
    # The current head, which can differ from the head this net was scheduled for.
    head_sha = (pr.get("head") or {}).get("sha") or ""
    if state.own_record is None and stored is not None:
        if stored.get(PINNED_ROUTED_HEAD) == head_sha:
            return
        if stored.get("status") == STATUS_ROUTING:
            # Another task holds a claim on the pull request.
            return
    pr_obj = review_path.upsert_pull_request(repo_config, pr)
    _claim_and_route(client, state, pr_obj, pr, head_sha=head_sha, trigger=TRIGGER_SAFETY_NET, task_id=task_id)
