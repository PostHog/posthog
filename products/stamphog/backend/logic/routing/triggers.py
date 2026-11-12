"""What each routing trigger decides: a pull request event, a finished review, a retracted approval, and the safety net.

Every trigger takes the same path. It reads the stored record and lets an own claim continue from
its last saved step. Then its guards decide on the record and the live pull request. Then
`_execute` claims the pull request with a compare-and-swap, or makes the head wait, and
`service.route_claimed` plans, saves the plan, and makes the GitHub writes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

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
    TRIGGER_APPROVAL_RETRACTED,
    TRIGGER_EXTERNAL_REVIEW,
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


class WillReview(Protocol):
    """Whether the review path is expected to give a verdict on the live pull request.

    ``count_silent`` counts the silent review that a clean PostHog Review run can start. Without it,
    the answer is whether a visible review comes, such as for the trigger label.
    """

    def __call__(self, repo_config: StamphogRepoConfig, pr: dict[str, Any], *, count_silent: bool) -> bool: ...


@frozen
class FinishedReview:
    """The latest finished review of one head, as routing reads it."""

    # The routing outcome: see `verdict_outcome`.
    outcome: str
    # Whether the run was silent. Nothing reviews a head again after a silent WAIT.
    silent: bool


@frozen
class ReviewPath:
    """What routing needs from the review path. The task module owns these and passes them in."""

    will_review: WillReview
    # Schedules the safety net for (repo_config, pr_number).
    schedule_safety_net: Callable[[StamphogRepoConfig, int], None]
    # The latest finished review of (repo_config, pr_number, head_sha), or None.
    finished_review: Callable[[StamphogRepoConfig, int, str], FinishedReview | None]
    # Whether (repo_config, pr_number, head_sha) has a review that is not superseded, finished or not.
    has_review: Callable[[StamphogRepoConfig, int, str], bool]
    # Whether a stamphog approval that nobody dismissed covers (repo_config, pr_number, head_sha), as posted or
    # retained through a clean base merge.
    approval_stands: Callable[[StamphogRepoConfig, int, str], bool]


def verdict_outcome(status: ReviewRunStatus, verdict: ReviewVerdict) -> str:
    """The routing outcome of a finished run: approved, refused, escalate, wait, gated or failed."""
    if status in (ReviewRunStatus.FAILED, ReviewRunStatus.GATED):
        return status.value
    return verdict.value


def _reviews_again(outcome: str, *, silent: bool) -> bool:
    # Stamphog re-reviews after a visible WAIT. Nothing re-reviews after a silent one, so it routes like a refusal.
    return outcome == ReviewVerdict.WAIT and not silent


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


def _finished_review_step(
    pr: dict[str, Any], state: _State, *, head_sha: str, mode: RoutingMode, review_path: ReviewPath
) -> _Step | None:
    """Route the head by its finished review, or None while it has none that ends the wait."""
    finished = review_path.finished_review(state.repo_config, state.pr_number, head_sha)
    if finished is None or _reviews_again(finished.outcome, silent=finished.silent):
        return None
    outcome = finished.outcome
    # A retraction after the review, such as a base retarget, leaves the approving run as the head's latest finished
    # review. Only an approval that still stands may hold the head to its pinned owners, so the head keeps waiting.
    if outcome == ReviewVerdict.APPROVED and not review_path.approval_stands(
        state.repo_config, state.pr_number, head_sha
    ):
        return None
    scope = SCOPE_PINNED if outcome == ReviewVerdict.APPROVED else SCOPE_FULL
    return _Step(pr=pr, head_sha=head_sha, mode=mode, trigger=verdict_trigger(outcome), scope=scope)


def _event_step(client: StamphogGitHubClient, state: _State, *, action: str, review_path: ReviewPath) -> _Step | None:
    repo_config = state.repo_config
    mode = RoutingMode(repo_config.routing_mode)
    # The live PR, not the payload: a draft toggle or a close can land between the two.
    pr = _live_head(client, repo_config, state.pr_number)
    if pr is None:
        return None
    head_sha = _head_sha(pr)
    record = state.record
    if (
        mode == RoutingMode.FALLBACK
        and record is not None
        and record.get("head_sha") == head_sha
        and record.get("status") == STATUS_WAITING
        and not record.get(FULL_ROUTED_HEAD)
    ):
        # A verdict that finished while the pull request was a draft found no live head to route, and the safety
        # net can have fired in that time too. When the pull request is ready again, nothing else routes the head.
        step = _finished_review_step(pr, state, head_sha=head_sha, mode=mode, review_path=review_path)
        if step is None:
            # A net that fired during the draft found no live head and scheduled nothing, so the head needs a new one.
            review_path.schedule_safety_net(repo_config, state.pr_number)
        return step
    if record is not None and record.get("head_sha") == head_sha:
        # Both modes route once per head, whatever started it. The `opened` task reads the live pull
        # request, so it already routes a draft marked ready before the task ran, and the
        # `ready_for_review` delivery for that head must not request the same owners again. A waiting
        # record left by FALLBACK requested nobody, so ALWAYS still routes that head.
        if mode == RoutingMode.FALLBACK or record.get("status") != STATUS_WAITING:
            return None
    if mode == RoutingMode.FALLBACK and record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    wait = mode == RoutingMode.FALLBACK and review_path.will_review(repo_config, pr, count_silent=True)
    if wait:
        # A fast verdict can land before this task stores a record, and the verdict task drops it as a PR that
        # opened before routing was on. So a head that already has a verdict routes by it instead of waiting.
        step = _finished_review_step(pr, state, head_sha=head_sha, mode=mode, review_path=review_path)
        if step is not None:
            return step
    return _Step(pr=pr, head_sha=head_sha, mode=mode, trigger=action, wait=wait)


def _schedule_net_after_partial_pins(repo_config: StamphogRepoConfig, pr_number: int, review_path: ReviewPath) -> None:
    # The net of the opening event can be gone already, so a pinned routing that can have missed a
    # pin needs a net of its own to route the head in full.
    record = stored_routing(repo_config, pr_number)
    if record is not None and record.get("status") == STATUS_DONE and pinned_on_partial_data(record):
        review_path.schedule_safety_net(repo_config, pr_number)


def _full_step_on_live_head(
    pr: dict[str, Any], state: _State, *, trigger: str, review_path: ReviewPath
) -> _Step | None:
    """Route the live head in full, for a waiting head that the author pushed past or that gets no silent review.

    A push to a pull request is not a ready event, so nothing starts a silent review of the newer head, and it
    would otherwise wait for the safety net. A review of the live head, or a visible one that comes for it such
    as for the trigger label, routes it by its verdict instead.
    """
    live_head_sha = _head_sha(pr)
    if review_path.has_review(state.repo_config, state.pr_number, live_head_sha):
        return None
    if review_path.will_review(state.repo_config, pr, count_silent=False):
        return None
    return _Step(pr=pr, head_sha=live_head_sha, mode=RoutingMode.FALLBACK, trigger=trigger)


def _external_review_step(
    client: StamphogGitHubClient, state: _State, *, head_sha: str, review_path: ReviewPath
) -> _Step | None:
    record = state.record
    if record is None:
        # ReviewHog reports from the same delivery as the opening event, so the report can come before the
        # event saves its waiting record. The task tries again soon.
        raise RoutingBusy(f"no routing record of PR {state.pr_number} yet")
    if record.get("status") != STATUS_WAITING or record.get(FULL_ROUTED_HEAD):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    # The record waits on the reported head, or on the live head because the author pushed before the opening
    # event read the pull request. Nothing starts a silent review of a pushed head in either case. A record on
    # any other head belongs to another report.
    if record.get("head_sha") not in (head_sha, _head_sha(pr)):
        return None
    return _full_step_on_live_head(pr, state, trigger=TRIGGER_EXTERNAL_REVIEW, review_path=review_path)


def route_after_external_review(
    repo_config: StamphogRepoConfig, *, pr_number: int, head_sha: str, task_id: str, review_path: ReviewPath
) -> None:
    """Route a waiting FALLBACK head in full, because ReviewHog will not start a silent review of it.

    With the clean-review switch on, a head waits for that silent review. Without this call it waits
    for the safety net. Any other state means another trigger already decides the head, so this does
    nothing. ``task_id`` is the Celery task id, which a retry of the same task keeps.
    """
    if repo_config.routing_mode != RoutingMode.FALLBACK or not repo_config.review_on_clean_external_review:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    step = _external_review_step(client, state, head_sha=head_sha, review_path=review_path)
    # A record that changed since the read is no longer waiting on this head, so another task decides it.
    _execute(client, state, step, review_path, retry_when_busy=False)


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


def _is_pinned_done(record: dict[str, Any]) -> bool:
    return record.get("status") == STATUS_DONE and record.get("scope") == SCOPE_PINNED


def _reopens_pinned(at_head: dict[str, Any], outcome: str) -> bool:
    # A re-review of the same head, after a base retarget, a manual request or the trigger label, dismissed the
    # approval before it ran. Its non-approval still owes the full routing that the pinned-only routing left out.
    # A visible WAIT makes the head wait again, because the next verdict can be another WAIT and only the safety
    # net routes the head after that.
    return outcome != ReviewVerdict.APPROVED and _is_pinned_done(at_head)


def _owes_live_head(record: dict[str, Any], *, head_sha: str, live_head_sha: str) -> bool:
    """Whether a verdict for a head that the author pushed past still owes a routing of the live head."""
    if record.get("status") == STATUS_WAITING:
        # The record waits on the old head, or on the live head when the opening event read the pull request
        # after the push.
        return record.get("head_sha") in (head_sha, live_head_sha)
    # The approval behind a pinned-only routing covers its own head only, and an unlabeled push starts no review.
    return _is_pinned_done(record) and record.get(PINNED_ROUTED_HEAD) != live_head_sha


def _verdict_step(
    client: StamphogGitHubClient,
    state: _State,
    *,
    head_sha: str,
    outcome: str,
    silent: bool,
    review_path: ReviewPath,
) -> _Step | None:
    if state.stored is None:
        # No routing event ran for this PR, so it opened before routing was on and got its reviewers elsewhere.
        # Routing it now would request again owners its author removed. A dead first claim still counts as a
        # record, and an opening event that runs after this verdict routes by it.
        return None
    record = state.record
    if record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    at_head = record if record is not None and record.get("head_sha") == head_sha else None
    if at_head is not None and at_head.get("status") != STATUS_WAITING and not _reopens_pinned(at_head, outcome):
        # Another task already routed or claimed this head.
        return None
    wait = _reviews_again(outcome, silent=silent)
    if wait and at_head is not None and at_head.get("status") == STATUS_WAITING:
        # The safety net already covers this head.
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    if _head_sha(pr) != head_sha:
        # In label mode a push to an unlabeled pull request supersedes no run, so a run of the old head can
        # still end here. Its verdict, an approval too, says nothing about the live head.
        if record is None or not _owes_live_head(record, head_sha=head_sha, live_head_sha=_head_sha(pr)):
            return None
        return _full_step_on_live_head(pr, state, trigger=verdict_trigger(outcome), review_path=review_path)
    return _Step(
        pr=pr,
        head_sha=head_sha,
        mode=RoutingMode.FALLBACK,
        trigger=verdict_trigger(outcome),
        wait=wait,
        scope=SCOPE_PINNED if outcome == ReviewVerdict.APPROVED else SCOPE_FULL,
    )


def route_after_verdict(
    *,
    team_id: int,
    repo_config_id: str,
    pr_number: int,
    head_sha: str,
    outcome: str,
    silent: bool,
    task_id: str,
    review_path: ReviewPath,
) -> None:
    """Route a FALLBACK pull request once stamphog's review of ``head_sha`` ended.

    ``silent`` says the review was a silent one, whose WAIT nothing reviews again. ``task_id`` is the
    Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
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
        step = _verdict_step(client, state, head_sha=head_sha, outcome=outcome, silent=silent, review_path=review_path)
        _execute(client, state, step, review_path, retry_when_busy=True)
    _schedule_net_after_partial_pins(repo_config, pr_number, review_path)


def _safety_net_step(client: StamphogGitHubClient, state: _State, *, review_path: ReviewPath) -> _Step | None:
    record = state.record
    if record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    # The current head, which can differ from the head this net was scheduled for.
    head_sha = _head_sha(pr)
    # A record that waits again on its approved head took a WAIT after the approval, which the WAIT's run dismissed.
    if record is not None and record.get(PINNED_ROUTED_HEAD) == head_sha and record.get("status") != STATUS_WAITING:
        return None
    # A clean base merge keeps the approval on a new head without a routing of that head. Its pinned owners are those
    # of the approved head, because the merge changed none of the pull request's own files.
    if (
        record is not None
        and record.get(PINNED_ROUTED_HEAD)
        and record.get("status") != STATUS_WAITING
        and review_path.approval_stands(state.repo_config, state.pr_number, head_sha)
    ):
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
    step = _safety_net_step(client, state, review_path=review_path)
    _execute(client, state, step, review_path, retry_when_busy=False)


def _retracted_approval_step(client: StamphogGitHubClient, state: _State, *, review_path: ReviewPath) -> _Step | None:
    record = state.record
    if record is None or record.get(FULL_ROUTED_HEAD):
        return None
    if not _is_pinned_done(record):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    live_head_sha = _head_sha(pr)
    # The task carries no identity of the approval it was queued for. A review that approved the live head after
    # that retraction already routed it, so the retraction is stale.
    if review_path.approval_stands(state.repo_config, state.pr_number, live_head_sha):
        return None
    # The payload can admit a review that a later gate refuses, such as the author's write permission, and then
    # no verdict routes the head. The net routes it in that case, and does nothing once a routing covers the head.
    review_path.schedule_safety_net(state.repo_config, state.pr_number)
    if live_head_sha != record.get("head_sha"):
        return _full_step_on_live_head(pr, state, trigger=TRIGGER_APPROVAL_RETRACTED, review_path=review_path)
    # A base retarget retracts the approval of the head that the run reviewed, and that run still counts as a
    # review of the head. Only a visible review judges the retargeted diff, so the head waits for its verdict. The
    # waiting record lets the net route the head when a later gate refuses that review.
    wait = review_path.will_review(state.repo_config, pr, count_silent=False)
    return _Step(
        pr=pr, head_sha=live_head_sha, mode=RoutingMode.FALLBACK, trigger=TRIGGER_APPROVAL_RETRACTED, wait=wait
    )


def route_after_approval_retracted(
    *, team_id: int, repo_config_id: str, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Route a FALLBACK pull request in full after a retraction removed the approval that held it to its pinned owners.

    A push to an unlabeled pull request, or a base retarget, retracts the approval and starts no review, so no
    verdict comes to upgrade the pinned-only routing. A review of the live head, or a visible one that comes for
    it such as for the trigger label, routes it by its verdict instead. ``task_id`` is the Celery task id, which a
    retry of the same task keeps, so a retry knows its own claim.
    """
    repo_config = _fallback_repo_config(team_id, repo_config_id)
    if repo_config is None:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    if is_foreign_claim(state.stored, task_id):
        # The claim can end in a pinned-only routing, which this retraction still upgrades, so decide after it ends.
        raise RoutingBusy(f"another task holds the routing claim of PR {pr_number}")
    step = _retracted_approval_step(client, state, review_path=review_path)
    _execute(client, state, step, review_path, retry_when_busy=True)
