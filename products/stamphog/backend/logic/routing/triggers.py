"""What each routing trigger decides: a pull request event, a finished review, and the safety net.

Every trigger takes the same path. It reads the stored record and lets an own claim continue from
its last saved step. Then its guards decide on the record and the live pull request. Then
`_execute` claims the pull request with a compare-and-swap, or makes the head wait, and
`service.route_claimed` plans, saves the plan, and makes the GitHub writes.
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
    SCOPE_FULL,
    SCOPE_PINNED,
    STATUS_DONE,
    STATUS_WAITING,
    TRIGGER_SAFETY_NET,
    RoutingBusy,
    claim_routing,
    effective_record,
    is_foreign_claim,
    is_own_claim,
    live_pr_skip_reason,
    pinned_on_partial_data,
    release_claim,
    resume_own_claim,
    route_claimed,
    routing_pull_request,
    save_waiting,
    stored_routing,
    verdict_trigger,
)
from products.stamphog.backend.models import StamphogRepoConfig

logger = structlog.get_logger(__name__)


@frozen
class ReviewPath:
    """What routing needs from the review path. The task module owns these and passes them in."""

    # Whether the review path is expected to give a verdict on the live pull request.
    will_review: Callable[[StamphogRepoConfig, dict[str, Any]], bool]
    # Schedules the safety net for (repo_config, pr_number).
    schedule_safety_net: Callable[[StamphogRepoConfig, int], None]
    # The routing outcome of the latest finished review of (repo_config, pr_number, head_sha), or None.
    finished_outcome: Callable[[StamphogRepoConfig, int, str], str | None]


def verdict_outcome(status: ReviewRunStatus, verdict: ReviewVerdict) -> str:
    """The routing outcome of a finished run: approved, refused, escalate, wait, gated or failed."""
    if status in (ReviewRunStatus.FAILED, ReviewRunStatus.GATED):
        return status.value
    return verdict.value


@frozen
class _State:
    """The stored routing record of one pull request, as one task sees it."""

    repo_config: StamphogRepoConfig
    pr_number: int
    task_id: str
    # The stored record as it is, which every compare-and-swap expects.
    stored: dict[str, Any] | None
    # The record the guards decide on: see `service.effective_record`.
    record: dict[str, Any] | None


@frozen
class _Step:
    """What the guards decided for the live pull request."""

    pr: dict[str, Any]
    head_sha: str
    mode: RoutingMode
    trigger: str
    # FALLBACK only: the head waits for stamphog's verdict instead of routing now.
    wait: bool = False
    scope: str = SCOPE_FULL


def _load_state(repo_config: StamphogRepoConfig, pr_number: int, task_id: str) -> _State:
    stored = stored_routing(repo_config, pr_number)
    return _State(
        repo_config=repo_config,
        pr_number=pr_number,
        task_id=task_id,
        stored=stored,
        record=effective_record(stored, task_id),
    )


def _resume(client: StamphogGitHubClient, state: _State) -> bool:
    """Continue what an earlier attempt of this task saved. True when nothing is left to do."""
    if state.stored is None or not is_own_claim(state.stored, state.task_id):
        return False
    return resume_own_claim(client, routing_pull_request(state.repo_config, state.pr_number), state.stored)


def _execute(
    client: StamphogGitHubClient,
    state: _State,
    step: _Step | None,
    review_path: ReviewPath,
    *,
    retry_when_busy: bool,
) -> None:
    """Claim and route, or make the head wait, as ``step`` says.

    A live claim of another task, or a record that changed since this task read it, raises
    `RoutingBusy` when ``retry_when_busy`` is set, so the task tries again later. Otherwise it
    returns, because another task already handles the pull request.
    """
    if step is None:
        if state.stored is not None and is_own_claim(state.stored, state.task_id):
            # An earlier attempt claimed, and the guards no longer route: give the record back.
            release_claim(routing_pull_request(state.repo_config, state.pr_number), state.stored)
        return
    if is_foreign_claim(state.stored, state.task_id):
        if retry_when_busy:
            raise RoutingBusy(f"another task holds the routing claim of PR {state.pr_number}")
        # The claiming task can still run out of retries, so the safety net checks again later.
        review_path.schedule_safety_net(state.repo_config, state.pr_number)
        return

    pr_obj = routing_pull_request(state.repo_config, state.pr_number)
    if step.wait:
        # Scheduled before the record is saved, so a retry after a failed schedule schedules again.
        # A second safety net is harmless: only one task can claim the pull request.
        review_path.schedule_safety_net(state.repo_config, state.pr_number)
        won = save_waiting(
            pr_obj, expected=state.stored, previous=state.record, head_sha=step.head_sha, trigger=step.trigger
        )
        claim = None
    else:
        claim = claim_routing(
            pr_obj,
            expected=state.stored,
            previous=state.record,
            head_sha=step.head_sha,
            mode=step.mode,
            trigger=step.trigger,
            scope=step.scope,
            claimed_by=state.task_id,
        )
        won = claim is not None
    if not won:
        if retry_when_busy:
            raise RoutingBusy(f"the routing record of PR {state.pr_number} changed during the decision")
        return
    if claim is not None:
        route_claimed(client, pr_obj, step.pr, claim=claim)


def _head_sha(pr: dict[str, Any]) -> str:
    return (pr.get("head") or {}).get("sha") or ""


def _live_head(client: StamphogGitHubClient, repo_config: StamphogRepoConfig, pr_number: int) -> dict[str, Any] | None:
    """The live pull request, or None when it is closed or a draft."""
    pr = client.get_pr(repo_config.repository, pr_number)
    reason = live_pr_skip_reason(pr)
    if reason is not None:
        logger.info(
            "stamphog_reviewer_routing_skipped", repo=repo_config.repository, pr_number=pr_number, reason=reason
        )
        return None
    return pr


def _event_step(client: StamphogGitHubClient, state: _State, *, action: str, review_path: ReviewPath) -> _Step | None:
    repo_config = state.repo_config
    mode = RoutingMode(repo_config.routing_mode)
    # The live PR, not the payload: a draft toggle or a close can land between the two.
    pr = _live_head(client, repo_config, state.pr_number)
    if pr is None:
        return None
    head_sha = _head_sha(pr)
    record = state.record
    if record is not None and record.get("head_sha") == head_sha:
        # ALWAYS routes once per head and action. FALLBACK routes once per head, whatever started it.
        if mode == RoutingMode.FALLBACK or record.get("trigger") == action:
            return None
    if mode == RoutingMode.FALLBACK and record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    wait = mode == RoutingMode.FALLBACK and review_path.will_review(repo_config, pr)
    if wait:
        # A fast verdict can land before this task stores a record, and the verdict task drops it as a PR that
        # opened before routing was on. So a head that already has a verdict routes by it instead of waiting.
        outcome = review_path.finished_outcome(repo_config, state.pr_number, head_sha)
        if outcome is not None and outcome != ReviewVerdict.WAIT:
            scope = SCOPE_PINNED if outcome == ReviewVerdict.APPROVED else SCOPE_FULL
            return _Step(pr=pr, head_sha=head_sha, mode=mode, trigger=verdict_trigger(outcome), scope=scope)
    return _Step(pr=pr, head_sha=head_sha, mode=mode, trigger=action, wait=wait)


def _schedule_net_after_partial_pins(repo_config: StamphogRepoConfig, pr_number: int, review_path: ReviewPath) -> None:
    # The net of the opening event can be gone already, so a pinned routing that can have missed a
    # pin needs a net of its own to route the head in full.
    record = stored_routing(repo_config, pr_number)
    if record is not None and record.get("status") == STATUS_DONE and pinned_on_partial_data(record):
        review_path.schedule_safety_net(repo_config, pr_number)


def route_on_pull_request_event(
    repo_config: StamphogRepoConfig, *, action: str, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Route a pull request that opened or became ready, or make it wait for the verdict.

    The caller checks that ``action`` is a routing action. ``task_id`` is the Celery task id, which
    a retry of the same task keeps, so a retry knows its own claim.
    """
    if repo_config.routing_mode == RoutingMode.OFF:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if not _resume(client, state):
        step = _event_step(client, state, action=action, review_path=review_path)
        _execute(client, state, step, review_path, retry_when_busy=True)
    # An approval that came before this event routes the pinned owners here, and the verdict task found no
    # record to give that routing a safety net.
    _schedule_net_after_partial_pins(repo_config, pr_number, review_path)


def _fallback_repo_config(team_id: int, repo_config_id: str) -> StamphogRepoConfig | None:
    repo_config = (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(id=repo_config_id)
        .first()
    )
    if repo_config is None or repo_config.routing_mode != RoutingMode.FALLBACK:
        return None
    return repo_config


def _upgrades_pinned(at_head: dict[str, Any], outcome: str) -> bool:
    # A re-review of the same head, after a base retarget or a manual request, can withdraw the
    # approval. Its non-approval still owes the full routing that the pinned-only routing left out.
    return (
        outcome not in (ReviewVerdict.APPROVED, ReviewVerdict.WAIT)
        and at_head.get("status") == STATUS_DONE
        and at_head.get("scope") == SCOPE_PINNED
    )


def _verdict_step(client: StamphogGitHubClient, state: _State, *, head_sha: str, outcome: str) -> _Step | None:
    if state.stored is None:
        # No routing event ran for this PR, so it opened before routing was on and got its reviewers elsewhere.
        # Routing it now would request again owners its author removed. A dead first claim still counts as a
        # record, and an opening event that runs after this verdict routes by it.
        return None
    record = state.record
    if record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    at_head = record if record is not None and record.get("head_sha") == head_sha else None
    if at_head is not None and at_head.get("status") != STATUS_WAITING and not _upgrades_pinned(at_head, outcome):
        # Another task already routed or claimed this head.
        return None
    if outcome == ReviewVerdict.WAIT and at_head is not None:
        # Stamphog re-reviews after a WAIT. The safety net already covers this head.
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None or _head_sha(pr) != head_sha:
        return None
    return _Step(
        pr=pr,
        head_sha=head_sha,
        mode=RoutingMode.FALLBACK,
        trigger=verdict_trigger(outcome),
        wait=outcome == ReviewVerdict.WAIT,
        scope=SCOPE_PINNED if outcome == ReviewVerdict.APPROVED else SCOPE_FULL,
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
    repo_config = _fallback_repo_config(team_id, repo_config_id)
    if repo_config is None:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if not _resume(client, state):
        if is_foreign_claim(state.stored, task_id):
            # The claim can end in a pinned-only routing that this verdict still upgrades, so decide after it ends.
            raise RoutingBusy(f"another task holds the routing claim of PR {pr_number}")
        step = _verdict_step(client, state, head_sha=head_sha, outcome=outcome)
        _execute(client, state, step, review_path, retry_when_busy=True)
    _schedule_net_after_partial_pins(repo_config, pr_number, review_path)


def _safety_net_step(client: StamphogGitHubClient, state: _State) -> _Step | None:
    record = state.record
    if record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    # The current head, which can differ from the head this net was scheduled for.
    head_sha = _head_sha(pr)
    if record is not None and record.get(PINNED_ROUTED_HEAD) == head_sha:
        return None
    return _Step(pr=pr, head_sha=head_sha, mode=RoutingMode.FALLBACK, trigger=TRIGGER_SAFETY_NET)


def route_on_safety_net(
    *, team_id: int, repo_config_id: str, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Route a FALLBACK pull request in full on its current head, unless it was already routed.

    ``task_id`` is the Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    repo_config = _fallback_repo_config(team_id, repo_config_id)
    if repo_config is None:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    step = _safety_net_step(client, state)
    _execute(client, state, step, review_path, retry_when_busy=False)
