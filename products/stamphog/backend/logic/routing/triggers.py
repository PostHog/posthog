"""What each routing trigger decides: a pull request event, a finished review, a retracted approval, and the safety net.

Every trigger takes the same path. It reads the stored record and lets an own claim continue from
its last saved step. Then its guards decide on the record and the live pull request. Then
`_execute` claims the pull request with a compare-and-swap, or makes the head wait, and
`service.route_claimed` plans, saves the plan, and makes the GitHub writes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from django.db import router

import structlog

from posthog.dataclasses import frozen

from products.stamphog.backend.facade.enums import ReviewRunStatus, ReviewVerdict, RoutingMode
from products.stamphog.backend.logic.attestation_checks import AttestationCheck, all_reported
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.routing.attestation import attestation_checks_to_wait_for, attestation_proven
from products.stamphog.backend.logic.routing.service import (
    FULL_ROUTED_HEAD,
    PINNED_ROUTED_HEAD,
    REQUESTED_OWNERS,
    ROUTING_SAFETY_NET_SECONDS,
    SCOPE_ATTESTED,
    SCOPE_FULL,
    SCOPE_PINNED,
    STATUS_DONE,
    STATUS_WAITING,
    TRIGGER_APPROVAL_RETRACTED,
    TRIGGER_ATTESTATION,
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
    waiting_attestation_checks,
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
    # Schedules poll number `poll` for the attestation checks of (repo_config, pr_number, head_sha, poll). It schedules
    # nothing past the last poll, and the safety net routes the head after that.
    schedule_attestation_poll: Callable[[StamphogRepoConfig, int, str, int], None]
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
    # The head waits instead of routing now: for stamphog's verdict, or for `attestation_checks` when there are any.
    wait: bool = False
    scope: str = SCOPE_FULL
    attestation_checks: tuple[AttestationCheck, ...] = ()


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
        if step.attestation_checks:
            review_path.schedule_attestation_poll(state.repo_config, state.pr_number, step.head_sha, 1)
        won = save_waiting(
            pr_obj,
            expected=state.stored,
            previous=state.record,
            head_sha=step.head_sha,
            mode=step.mode,
            trigger=step.trigger,
            attestation_checks=step.attestation_checks,
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
        # record requested nobody, so ALWAYS still decides that head.
        if mode == RoutingMode.FALLBACK or record.get("status") != STATUS_WAITING:
            return None
    if mode == RoutingMode.ALWAYS:
        # A head that only pinned attestations cover waits for their checks, because a verified proof can leave the
        # owners unasked. A head that waits for them already, such as one marked ready again, waits anew.
        checks = attestation_checks_to_wait_for(client, repo_config.repository, pr)
        return _Step(pr=pr, head_sha=head_sha, mode=mode, trigger=action, wait=bool(checks), attestation_checks=checks)
    if record is not None and record.get(FULL_ROUTED_HEAD):
        return None
    wait = review_path.will_review(repo_config, pr, count_silent=True)
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
    return _Step(pr=pr, head_sha=live_head_sha, mode=RoutingMode(state.repo_config.routing_mode), trigger=trigger)


def _keeps_a_reviewer(pr: dict[str, Any], state: _State, *, review_path: ReviewPath) -> bool:
    """Whether the pull request keeps a reviewer when routing requests no unpinned owner.

    A pending review request that no routing of the pull request made counts, such as one that the author's bot
    made. A stamphog approval that stands over the head counts too.
    """
    routed = {owner.casefold() for owner in (state.record or {}).get(REQUESTED_OWNERS) or []}
    pending = [f"@{user.get('login')}" for user in pr.get("requested_reviewers") or []]
    pending += [str(team.get("slug")) for team in pr.get("requested_teams") or []]
    if any(reviewer.casefold() not in routed for reviewer in pending):
        return True
    return review_path.approval_stands(state.repo_config, state.pr_number, _head_sha(pr))


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


def _repo_config(team_id: int, repo_config_id: str) -> StamphogRepoConfig | None:
    return (
        StamphogRepoConfig.objects.for_team(team_id)
        .using(router.db_for_write(StamphogRepoConfig))
        .filter(id=repo_config_id)
        .first()
    )


def _is_attested_done(record: dict[str, Any]) -> bool:
    return record.get("status") == STATUS_DONE and record.get("scope") == SCOPE_ATTESTED


def routes_after_review(repo_config: StamphogRepoConfig, pr_number: int) -> bool:
    """Whether a finished review or a retracted approval can route the pull request, so a task is worth queueing.

    FALLBACK always can, and ALWAYS only after an attested routing, which counted on a reviewer that can go away.
    """
    if repo_config.routing_mode == RoutingMode.FALLBACK:
        return True
    if repo_config.routing_mode != RoutingMode.ALWAYS:
        return False
    record = stored_routing(repo_config, pr_number)
    return record is not None and record.get("scope") == SCOPE_ATTESTED


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


def _attested_verdict_step(
    client: StamphogGitHubClient,
    state: _State,
    *,
    head_sha: str,
    outcome: str,
    silent: bool,
    review_path: ReviewPath,
) -> _Step | None:
    """Route the live head of an attested pull request in full when a verdict leaves it without a reviewer."""
    if state.record is None or not _is_attested_done(state.record):
        return None
    if outcome == ReviewVerdict.APPROVED or _reviews_again(outcome, silent=silent):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None or _head_sha(pr) != head_sha:
        # The verdict says nothing about a newer head. Its own review or the approval retraction decides it.
        return None
    if _keeps_a_reviewer(pr, state, review_path=review_path):
        return None
    return _Step(pr=pr, head_sha=head_sha, mode=RoutingMode.ALWAYS, trigger=verdict_trigger(outcome))


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
    """Route a FALLBACK pull request once stamphog's review of ``head_sha`` ended, or an attested ALWAYS one.

    ``silent`` says the review was a silent one, whose WAIT nothing reviews again. ``task_id`` is the
    Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    repo_config = _repo_config(team_id, repo_config_id)
    if repo_config is None or repo_config.routing_mode == RoutingMode.OFF:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if not _resume(client, state):
        if is_foreign_claim(state.stored, task_id):
            # The claim can end in a pinned-only or an attested routing that this verdict still upgrades, so decide
            # after it ends.
            raise RoutingBusy(f"another task holds the routing claim of PR {pr_number}")
        if repo_config.routing_mode == RoutingMode.ALWAYS:
            step = _attested_verdict_step(
                client, state, head_sha=head_sha, outcome=outcome, silent=silent, review_path=review_path
            )
        else:
            step = _verdict_step(
                client, state, head_sha=head_sha, outcome=outcome, silent=silent, review_path=review_path
            )
        _execute(client, state, step, review_path, retry_when_busy=True)
    _schedule_net_after_partial_pins(repo_config, pr_number, review_path)


def _waited_for_the_net(record: dict[str, Any]) -> bool:
    """Whether the record has waited as long as a safety net delays, give or take a minute of scheduling."""
    waiting_since = record.get("waiting_since")
    if not isinstance(waiting_since, str):
        return True
    waited = datetime.now(UTC) - datetime.fromisoformat(waiting_since)
    return waited >= timedelta(seconds=ROUTING_SAFETY_NET_SECONDS - 60)


def _attestation_safety_net_step(client: StamphogGitHubClient, state: _State) -> _Step | None:
    """Route the live head in full when the checks of an ALWAYS head did not end its wait in time."""
    record = state.record
    if record is None or not waiting_attestation_checks(record):
        return None
    if not _waited_for_the_net(record):
        # The net carries no head, so it can belong to a head that the author pushed past. The wait of the pushed
        # head scheduled a net of its own.
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    return _Step(pr=pr, head_sha=_head_sha(pr), mode=RoutingMode.ALWAYS, trigger=TRIGGER_SAFETY_NET)


def _safety_net_step(client: StamphogGitHubClient, state: _State, *, review_path: ReviewPath) -> _Step | None:
    if state.repo_config.routing_mode == RoutingMode.ALWAYS:
        return _attestation_safety_net_step(client, state)
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
    """Route a pull request in full on its current head, unless it was already routed.

    FALLBACK routes a head that still waits for the verdict, and ALWAYS one that still waits for its attestation
    checks. ``task_id`` is the Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    repo_config = _repo_config(team_id, repo_config_id)
    if repo_config is None or repo_config.routing_mode == RoutingMode.OFF:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    step = _safety_net_step(client, state, review_path=review_path)
    _execute(client, state, step, review_path, retry_when_busy=False)


def _approval_can_still_come(pr: dict[str, Any], state: _State, *, review_path: ReviewPath) -> bool:
    """Whether stamphog can still approve the head: its review has not finished, or it reviews again after a WAIT."""
    review = review_path.finished_review(state.repo_config, state.pr_number, _head_sha(pr))
    if review is not None:
        return _reviews_again(review.outcome, silent=review.silent)
    return review_path.will_review(state.repo_config, pr, count_silent=False)


def _attestation_step(pr: dict[str, Any], head_sha: str, scope: str = SCOPE_FULL) -> _Step:
    return _Step(pr=pr, head_sha=head_sha, mode=RoutingMode.ALWAYS, trigger=TRIGGER_ATTESTATION, scope=scope)


def _attestation_wait_on_live_head(
    client: StamphogGitHubClient, state: _State, pr: dict[str, Any], *, trigger: str
) -> _Step:
    """Make a head the author pushed wait for its own attestation checks, or route it in full when none cover it.

    A proof covers the files of the head it names, so the proof of an earlier head says nothing about this one.
    """
    checks = attestation_checks_to_wait_for(client, state.repo_config.repository, pr)
    return _Step(
        pr=pr,
        head_sha=_head_sha(pr),
        mode=RoutingMode.ALWAYS,
        trigger=trigger,
        wait=bool(checks),
        attestation_checks=checks,
    )


def _attestation_poll_step(
    client: StamphogGitHubClient, state: _State, *, head_sha: str, poll: int, review_path: ReviewPath
) -> _Step | None:
    record = state.record
    checks = waiting_attestation_checks(record)
    if not checks or record is None or record.get("head_sha") != head_sha:
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    live_head_sha = _head_sha(pr)
    if live_head_sha != head_sha:
        return _attestation_wait_on_live_head(client, state, pr, trigger=TRIGGER_ATTESTATION)
    repository = state.repo_config.repository
    if not all_reported(client, repository, head_sha, checks, pr_number=state.pr_number):
        review_path.schedule_attestation_poll(state.repo_config, state.pr_number, head_sha, poll + 1)
        return None
    if not attestation_proven(client, repository, pr):
        return _attestation_step(pr, head_sha)
    # Read before the reviewer check: an approval that lands between the two reads then counts in one of them.
    approval_can_still_come = _approval_can_still_come(pr, state, review_path=review_path)
    if _keeps_a_reviewer(pr, state, review_path=review_path):
        return _attestation_step(pr, head_sha, scope=SCOPE_ATTESTED)
    if approval_can_still_come:
        # Stamphog reviews an admitted bot's pull request again only after the proof reported, so its approval
        # usually lands a few minutes after the check.
        review_path.schedule_attestation_poll(state.repo_config, state.pr_number, head_sha, poll + 1)
        return None
    return _attestation_step(pr, head_sha)


def route_after_attestation_poll(
    *,
    team_id: int,
    repo_config_id: str,
    pr_number: int,
    head_sha: str,
    poll: int,
    task_id: str,
    review_path: ReviewPath,
) -> None:
    """Decide an ALWAYS head that waits for its attestation checks, once every one of them reported.

    A verified proof of every changed file requests only the pinned owners while the pull request keeps a reviewer.
    Anything else routes in full. A check that did not report yet schedules the next poll. ``task_id`` is the Celery
    task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    repo_config = _repo_config(team_id, repo_config_id)
    if repo_config is None or repo_config.routing_mode != RoutingMode.ALWAYS:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    step = _attestation_poll_step(client, state, head_sha=head_sha, poll=poll, review_path=review_path)
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


def _attested_recheck_step(
    client: StamphogGitHubClient, state: _State, *, trigger: str, review_path: ReviewPath
) -> _Step | None:
    """Decide an attested pull request again after a push, a base retarget or a retracted approval.

    The pushed head waits for its own proof. On the same head, the head routes in full when its proof no longer
    covers the diff, which a base retarget changes, or when it is left without a reviewer.
    """
    record = state.record
    if record is None or not _is_attested_done(record):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None:
        return None
    live_head_sha = _head_sha(pr)
    if live_head_sha != record.get("head_sha"):
        return _attestation_wait_on_live_head(client, state, pr, trigger=trigger)
    if not attestation_proven(client, state.repo_config.repository, pr):
        return _Step(pr=pr, head_sha=live_head_sha, mode=RoutingMode.ALWAYS, trigger=trigger)
    if _keeps_a_reviewer(pr, state, review_path=review_path):
        return None
    # A base retarget retracts the approval of the attested head, and its run still counts as a review of the head.
    # Only a visible review judges the retargeted diff, and its verdict routes the head.
    if review_path.will_review(state.repo_config, pr, count_silent=False):
        return None
    return _Step(pr=pr, head_sha=live_head_sha, mode=RoutingMode.ALWAYS, trigger=trigger)


def route_after_approval_retracted(
    *, team_id: int, repo_config_id: str, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Route a FALLBACK pull request in full after a retraction removed the approval that held it to its pinned owners.

    A push to an unlabeled pull request, or a base retarget, retracts the approval and starts no review, so no
    verdict comes to upgrade the pinned-only routing. A review of the live head, or a visible one that comes for
    it such as for the trigger label, routes it by its verdict instead. An attested ALWAYS pull request waits for the
    proof of a pushed head, and routes the same way when the retraction leaves the same head without a reviewer. ``task_id`` is the Celery task id, which a retry of
    the same task keeps, so a retry knows its own claim.
    """
    repo_config = _repo_config(team_id, repo_config_id)
    if repo_config is None or repo_config.routing_mode == RoutingMode.OFF:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    if is_foreign_claim(state.stored, task_id):
        # The claim can end in a pinned-only or an attested routing, which this retraction still upgrades, so decide
        # after it ends.
        raise RoutingBusy(f"another task holds the routing claim of PR {pr_number}")
    if repo_config.routing_mode == RoutingMode.ALWAYS:
        step = _attested_recheck_step(client, state, trigger=TRIGGER_APPROVAL_RETRACTED, review_path=review_path)
    else:
        step = _retracted_approval_step(client, state, review_path=review_path)
    _execute(client, state, step, review_path, retry_when_busy=True)


def _head_change_step(client: StamphogGitHubClient, state: _State, *, review_path: ReviewPath) -> _Step | None:
    record = state.record
    if record is None:
        return None
    if _is_attested_done(record):
        return _attested_recheck_step(client, state, trigger=TRIGGER_ATTESTATION, review_path=review_path)
    if not waiting_attestation_checks(record):
        return None
    pr = _live_head(client, state.repo_config, state.pr_number)
    if pr is None or _head_sha(pr) == record.get("head_sha"):
        # The poll of the waiting head verifies the proof against the live diff, a retargeted one too.
        return None
    return _attestation_wait_on_live_head(client, state, pr, trigger=TRIGGER_ATTESTATION)


def route_after_head_change(
    repo_config: StamphogRepoConfig, *, pr_number: int, task_id: str, review_path: ReviewPath
) -> None:
    """Decide an attested ALWAYS pull request again after a push or a base retarget.

    A proof covers the diff of one head against one base, and the bot that pushed may hold no stamphog approval
    whose retraction would decide the pull request again. A pushed head waits for its own proof, and a retargeted
    head routes in full once its proof no longer covers the diff. ``task_id`` is the Celery task id, which a retry of
    the same task keeps, so a retry knows its own claim.
    """
    if repo_config.routing_mode != RoutingMode.ALWAYS:
        return
    client = StamphogGitHubClient(repo_config.installation_id)
    state = _load_state(repo_config, pr_number, task_id)
    if _resume(client, state):
        return
    if is_foreign_claim(state.stored, task_id):
        # The claim can end in an attested routing of the head this task comes too late for, so decide after it ends.
        raise RoutingBusy(f"another task holds the routing claim of PR {pr_number}")
    step = _head_change_step(client, state, review_path=review_path)
    _execute(client, state, step, review_path, retry_when_busy=True)
