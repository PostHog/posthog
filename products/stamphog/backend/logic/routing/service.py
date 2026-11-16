"""One reviewer routing run: owners of the changed code, the cut step, the review requests and the comment.

The repo's `routing_mode` decides when a run happens. ALWAYS routes when a pull request opens or
becomes ready. FALLBACK waits for stamphog's verdict on the head when stamphog will review it: an
approval requests only the pinned owners, any other outcome routes in full. Routing runs for bot
and fork pull requests too, like the CI assigner it replaces. Ownership is read from the default
branch, never from the pull request head, so a pull request cannot name its own reviewers.

Every run goes through one claim: a compare-and-swap on `PullRequest.routing` that names the Celery
task. The task then saves its plan, makes the GitHub writes, and finishes the comment. A retry of the
same task keeps the task id, so it finds its own claim and continues from the last saved step.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import router

import structlog
from owners_yaml import OwnersResolver, Resolution

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.utils import uuid7
from posthog.ownership.github_files import AuthenticatedRepoTree, GitHubFilesFetcher
from posthog.ph_client import ph_scoped_capture

from products.stamphog.backend.facade.enums import (
    LlmSkipReason,
    OwnerKind,
    RoutingMode,
    RoutingOwnerOutcome,
    RoutingOwnerReason,
    RoutingScope,
)
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.routing.candidates import (
    ChangedFile,
    OwnerCandidate,
    find_candidates,
    paths_to_resolve,
)
from products.stamphog.backend.logic.routing.comment import (
    ROUTING_COMMENT_MARKER,
    render_approved_routing_comment,
    render_routing_comment,
)
from products.stamphog.backend.logic.routing.cut import CUT_MODEL, RoutingDecision, decide_cuts, keep_pinned
from products.stamphog.backend.logic.routing.model import GatewayCutModel
from products.stamphog.backend.logic.routing.run_log import record_routing_run
from products.stamphog.backend.logic.scrubbing import neutralize_active_markdown, scrub_credentials
from products.stamphog.backend.models import PullRequest, StamphogRepoConfig

logger = structlog.get_logger(__name__)

ROUTING_EVENT = "stamphog_reviewer_routing_completed"
# FALLBACK only: the head waits for stamphog's verdict or for the safety net, whichever comes first.
STATUS_WAITING = "waiting"
# A task claimed the pull request and its routing is running. The record holds the plan once
# `planned_at` is set, and the plan is saved before any GitHub write.
STATUS_ROUTING = "routing"
# A record stays REQUESTED between the review requests and the comment, so a retry finishes the
# comment without requesting anybody a second time.
STATUS_REQUESTED = "requested"
STATUS_DONE = "done"
_CLAIMED_STATUSES = frozenset({STATUS_ROUTING, STATUS_REQUESTED})
# A claim older than this counts as abandoned, so a task that died does not block the pull request
# for good. It sits far above the time a task needs to finish, retries included.
CLAIM_STALE_AFTER = timedelta(hours=2)

TRIGGER_SAFETY_NET = "safety_net"
SCOPE_FULL = RoutingScope.FULL.value
SCOPE_PINNED = RoutingScope.PINNED.value

# PR-level marks, carried over every later record of the pull request. FALLBACK routes in full at
# most once per pull request. `pinned_routed_head` is the latest approved head that got its pinned
# owners requested, and `requested_owners` is every owner any routing of the pull request requested.
FULL_ROUTED_HEAD = "full_routed_head"
PINNED_ROUTED_HEAD = "pinned_routed_head"
REQUESTED_OWNERS = "requested_owners"
# Whether the latest finished routing left a routing comment on the pull request. Only then does a
# routing that writes no comment page through the comments to delete it.
COMMENT_POSTED = "comment_posted"
_PR_MARK_KEYS = (
    FULL_ROUTED_HEAD,
    "full_routed_at",
    PINNED_ROUTED_HEAD,
    "pinned_routed_at",
    REQUESTED_OWNERS,
    COMMENT_POSTED,
)


class RoutingBusy(Exception):
    """Another task holds the routing claim of the pull request, or changed its record first."""


def verdict_trigger(outcome: str) -> str:
    return f"verdict:{outcome}"


def live_pr_skip_reason(pr: Mapping[str, Any]) -> str | None:
    """Why the live pull request does not route at all, or None when it does."""
    if pr.get("state") != "open":
        return "not_open"
    if pr.get("draft"):
        return "draft"
    return None


def is_fork(pr: Mapping[str, Any], repository: str) -> bool:
    # A deleted fork leaves no head repo, and it is still not the base repository.
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name") or ""
    return head_repo.casefold() != repository.casefold()


def fork_labels(repo_config: StamphogRepoConfig) -> dict[str, str]:
    """The repo's team slug -> label map. Entries that are not a string pair are ignored."""
    configured = repo_config.routing_fork_labels
    if not isinstance(configured, dict):
        return {}
    return {slug: label for slug, label in configured.items() if isinstance(slug, str) and isinstance(label, str)}


def stored_routing(repo_config: StamphogRepoConfig, pr_number: int) -> dict[str, Any] | None:
    """The latest routing record of the pull request. Writer-pinned, because it decides a GitHub write."""
    record = (
        PullRequest.objects.for_team(repo_config.team_id)
        .using(router.db_for_write(PullRequest))
        .filter(repo_config=repo_config, pr_number=pr_number)
        .values_list("routing", flat=True)
        .first()
    )
    return record if isinstance(record, dict) else None


def routing_pull_request(repo_config: StamphogRepoConfig, pr_number: int) -> PullRequest:
    """The pull request row that routing writes its record to, created bare when it is missing.

    Routing never writes `payload_updated_at` or the descriptive fields. The review path drops a
    webhook delivery older than `payload_updated_at`, so a live read stamped there would make it drop
    a delivery it has not processed yet. A bare row has a null clock, which the review path refreshes.
    """
    team_id = repo_config.team_id
    pr_obj, _ = (
        PullRequest.objects.for_team(team_id)
        .using(router.db_for_write(PullRequest))
        .get_or_create(repo_config=repo_config, pr_number=pr_number, defaults={"team_id": team_id})
    )
    # The caller read the config on the writer. A lazy load of the relation reads a replica, which can
    # lag behind a fork label change.
    pr_obj.repo_config = repo_config
    return pr_obj


def pinned_on_partial_data(record: Mapping[str, Any]) -> bool:
    """Whether a pinned routing planned from partial ownership data, which can miss a pin."""
    return record.get("scope") == SCOPE_PINNED and not (
        record.get("additions_resolved") and not record.get("files_truncated")
    )


def _is_claim(record: Mapping[str, Any] | None) -> bool:
    return record is not None and record.get("status") in _CLAIMED_STATUSES


def is_own_claim(record: Mapping[str, Any] | None, task_id: str) -> bool:
    return _is_claim(record) and bool(task_id) and record is not None and record.get("claimed_by") == task_id


def _is_stale_claim(record: Mapping[str, Any]) -> bool:
    try:
        claimed_at = datetime.fromisoformat(str(record.get("claimed_at") or ""))
    except ValueError:
        return True
    return datetime.now(UTC) - claimed_at > CLAIM_STALE_AFTER


def is_foreign_claim(record: Mapping[str, Any] | None, task_id: str) -> bool:
    """Whether another task holds a live claim on the pull request."""
    return (
        _is_claim(record) and not is_own_claim(record, task_id) and record is not None and not _is_stale_claim(record)
    )


def effective_record(record: dict[str, Any] | None, task_id: str) -> dict[str, Any] | None:
    """The record the guards decide on.

    A claim that has not reached its requests, and is this task's own or abandoned, counts as the
    record it replaced. So a retry or a takeover decides as if that claim never happened.
    """
    if record is None or record.get("status") != STATUS_ROUTING:
        return record
    if is_own_claim(record, task_id) or _is_stale_claim(record):
        previous = record.get("previous")
        return previous if isinstance(previous, dict) else None
    return record


def _pr_marks(previous: Mapping[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {}
    return {key: previous[key] for key in _PR_MARK_KEYS if key in previous}


def _replace_routing(pr_obj: PullRequest, *, expected: Mapping[str, Any] | None, record: dict[str, Any]) -> bool:
    """Write ``record`` only while the stored record still equals ``expected``.

    Event, verdict and safety-net tasks can fire at the same moment. Only one of them wins the
    compare and swap, so the pull request gets one set of review requests.
    """
    rows = PullRequest.objects.for_team(pr_obj.team_id).using(router.db_for_write(PullRequest)).filter(id=pr_obj.id)
    rows = rows.filter(routing__isnull=True) if expected is None else rows.filter(routing=expected)
    return rows.update(routing=record) == 1


def _save_claimed(pr_obj: PullRequest, record: dict[str, Any]) -> bool:
    """Write ``record`` only while the task in its `claimed_by` still holds the claim."""
    saved = (
        PullRequest.objects.for_team(pr_obj.team_id)
        .using(router.db_for_write(PullRequest))
        .filter(id=pr_obj.id, routing__claimed_by=record["claimed_by"])
        .update(routing=record)
        == 1
    )
    if not saved:
        logger.warning("stamphog_reviewer_routing_claim_lost", pr_number=pr_obj.pr_number)
    return saved


def _base_record(
    previous: Mapping[str, Any] | None, *, head_sha: str, mode: RoutingMode, trigger: str, status: str
) -> dict[str, Any]:
    return {**_pr_marks(previous), "head_sha": head_sha, "mode": mode.value, "trigger": trigger, "status": status}


def save_waiting(
    pr_obj: PullRequest,
    *,
    expected: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    head_sha: str,
    trigger: str,
) -> bool:
    """Make the head wait for the verdict. ``previous`` is the record whose marks carry over."""
    record = _base_record(
        previous, head_sha=head_sha, mode=RoutingMode.FALLBACK, trigger=trigger, status=STATUS_WAITING
    )
    record["waiting_since"] = datetime.now(UTC).isoformat()
    return _replace_routing(pr_obj, expected=expected, record=record)


def claim_routing(
    pr_obj: PullRequest,
    *,
    expected: Mapping[str, Any] | None,
    previous: Mapping[str, Any] | None,
    head_sha: str,
    mode: RoutingMode,
    trigger: str,
    scope: str,
    claimed_by: str,
) -> dict[str, Any] | None:
    """Claim the pull request for one task. Returns the claim, or None when another task changed the record first.

    ``previous`` is the record the guards decided on. The claim keeps it whole, so a retry or a
    takeover before the requests can decide on it again, or put it back with `release_claim`.
    """
    claim = _base_record(previous, head_sha=head_sha, mode=mode, trigger=trigger, status=STATUS_ROUTING)
    claim["scope"] = scope
    claim["claimed_by"] = claimed_by
    claim["claimed_at"] = datetime.now(UTC).isoformat()
    claim["previous"] = previous
    return claim if _replace_routing(pr_obj, expected=expected, record=claim) else None


def release_claim(pr_obj: PullRequest, claim: dict[str, Any]) -> None:
    """Put back the record that an own claim replaced, for a retry whose guards no longer route."""
    previous = claim.get("previous")
    restored = previous if isinstance(previous, dict) else None
    rows = PullRequest.objects.for_team(pr_obj.team_id).using(router.db_for_write(PullRequest)).filter(id=pr_obj.id)
    rows.filter(routing=claim).update(routing=restored)


class _SourceWithoutKinds:
    """An ownership source that hides `path_kind`, so the resolver reports no additions."""

    def __init__(self, files: AuthenticatedRepoTree) -> None:
        self._files = files

    def read(self, path: str) -> str | None:
        return self._files.read(path)

    def read_all(self, paths: list[str]) -> None:
        self._files.read_all(paths)


@frozen
class _Ownership:
    resolutions: dict[str, Resolution]
    # False when the owners of additions could not be read, so the run routes without their pins.
    additions_resolved: bool
    owners_sha: str | None


def _resolve_owners(client: StamphogGitHubClient, repository: str, files: Sequence[ChangedFile]) -> _Ownership:
    """Every path's resolution at one default-branch commit, and whether the owners of additions are part of it.

    The owners of additions are an extra. A failed kind lookup routes without their pins rather than
    failing the run; a failure of the plain ownership read raises.
    """
    fetcher = GitHubFilesFetcher.from_token(
        client.installation_token(),
        installation_id=client.installation_id,
        refresh=client.refresh_installation_token,
        # The author waits on the review requests.
        priority=Priority.NORMAL,
    )
    # The run requests reviewers once and never corrects them later, so it reads the head of this
    # run rather than a head another read cached a minute ago. One reader keeps every read on that
    # one commit.
    tree = AuthenticatedRepoTree(repository, fetcher, fresh_head=True)
    paths = paths_to_resolve(files)
    try:
        tree.prefetch_kinds(paths)
    except Exception:
        logger.warning("stamphog_reviewer_routing_additions_unavailable", exc_info=True)
        resolutions = OwnersResolver(source=_SourceWithoutKinds(tree)).map(paths)
        return _Ownership(resolutions=resolutions, additions_resolved=False, owners_sha=tree.head_sha)
    resolutions = OwnersResolver(source=tree).map(paths)
    return _Ownership(resolutions=resolutions, additions_resolved=True, owners_sha=tree.head_sha)


@frozen
class _Requests:
    users: list[str]
    teams: list[str]
    labeled_teams: list[str]
    labels: list[str]


def _plan_requests(kept: Sequence[OwnerCandidate], *, fork: bool, labels_by_team: Mapping[str, str]) -> _Requests:
    users = [candidate.owner.removeprefix("@") for candidate in kept if candidate.kind == OwnerKind.PERSON]
    teams = [candidate.owner for candidate in kept if candidate.kind == OwnerKind.TEAM]
    if not fork:
        return _Requests(users=users, teams=teams, labeled_teams=[], labels=[])
    labeled_teams = [team for team in teams if team in labels_by_team]
    return _Requests(
        users=users,
        teams=[team for team in teams if team not in labels_by_team],
        labeled_teams=labeled_teams,
        labels=list(dict.fromkeys(labels_by_team[team] for team in labeled_teams)),
    )


def _owner_outcome(
    owner: str, reason: RoutingOwnerReason, *, request_owners: set[str], labeled_teams: set[str]
) -> RoutingOwnerOutcome:
    """What the run does with one owner. GitHub can still refuse a request, which the run log adds."""
    if reason == RoutingOwnerReason.MODEL_CUT:
        return RoutingOwnerOutcome.CUT
    if reason == RoutingOwnerReason.STAMPHOG_APPROVED:
        return RoutingOwnerOutcome.NOT_REQUESTED
    if owner not in request_owners:
        # A pinned owner on an approval that an earlier routing of the pull request already requested.
        return RoutingOwnerOutcome.ALREADY_REQUESTED
    if owner in labeled_teams:
        return RoutingOwnerOutcome.LABELED
    return RoutingOwnerOutcome.REQUESTED


def _candidate_record(
    candidate: OwnerCandidate, decision: RoutingDecision, *, request_owners: set[str], labeled_teams: set[str]
) -> dict[str, Any]:
    reason = decision.reasons[candidate.owner]
    outcome = _owner_outcome(candidate.owner, reason, request_owners=request_owners, labeled_teams=labeled_teams)
    return {
        "owner": candidate.owner,
        "kind": candidate.kind.value,
        "lines": candidate.lines,
        "file_count": len(candidate.files),
        "pins": sorted(({"reason": pin.reason.value, "path": pin.path} for pin in candidate.pins), key=str),
        "files": [
            {
                "path": file.path,
                "previous_path": file.previous_path,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
            }
            for file in candidate.files
        ],
        "outcome": outcome.value,
        "reason": reason.value,
        "model_reason": decision.model_reasons.get(candidate.owner, ""),
    }


def _comment_body(decision: RoutingDecision, repository: str) -> str | None:
    if decision.llm_skipped == LlmSkipReason.STAMPHOG_APPROVED:
        body = render_approved_routing_comment() if decision.kept else None
    else:
        body = render_routing_comment(decision=decision, org=repository.split("/", 1)[0])
    if body is None:
        return None
    return neutralize_active_markdown(scrub_credentials(body))


def finish_comment(client: StamphogGitHubClient, pr_obj: PullRequest, record: dict[str, Any]) -> None:
    """Write or remove the routing comment, then mark the record done."""
    repository = pr_obj.repo_config.repository
    body = record.get("pending_comment")
    posted = False
    if isinstance(body, str) and body:
        client.upsert_sticky_comment(repository, pr_obj.pr_number, body, marker=ROUTING_COMMENT_MARKER)
        posted = True
    elif record.get(COMMENT_POSTED):
        # Nobody is cut now, so a comment from an earlier routing names cuts that no longer hold.
        client.delete_sticky_comment(repository, pr_obj.pr_number, marker=ROUTING_COMMENT_MARKER)
    done = {key: value for key, value in record.items() if key != "pending_comment"}
    # The run log already holds the file lists, and a large pull request would carry them on its row for good.
    done["candidates"] = [
        {key: value for key, value in candidate.items() if key != "files"} for candidate in record["candidates"]
    ]
    done["status"] = STATUS_DONE
    done[COMMENT_POSTED] = posted
    _save_claimed(pr_obj, done)


def _capture(repo_config: StamphogRepoConfig, record: dict[str, Any]) -> None:
    # Counts only: no title, path or reason leaves for analytics.
    properties: dict[str, Any] = {
        "stamphog_repo": repo_config.repository,
        "stamphog_team_id": repo_config.team_id,
        "stamphog_routing_mode": record["mode"],
        "stamphog_routing_trigger": record["trigger"],
        "stamphog_routing_scope": record["scope"],
        "stamphog_routing_fork": record["fork"],
        "stamphog_routing_candidates": len(record["candidates"]),
        "stamphog_routing_pinned": sum(1 for candidate in record["candidates"] if candidate["pins"]),
        "stamphog_routing_kept": len(record["kept"]),
        "stamphog_routing_cut": len(record["cut"]),
        "stamphog_routing_requested_teams": len(record["requested_teams"]),
        "stamphog_routing_requested_users": len(record["requested_users"]),
        "stamphog_routing_labeled_teams": len(record["labeled_teams"]),
        "stamphog_routing_refused": len(record["refused"]),
        "stamphog_routing_llm_skipped": record["llm_skipped"],
        "stamphog_routing_additions_resolved": record["additions_resolved"],
        "stamphog_routing_files_truncated": record["files_truncated"],
        "stamphog_routing_latency_ms": record["latency_ms"],
        "stamphog_routing_input_tokens": record["input_tokens"],
        "stamphog_routing_output_tokens": record["output_tokens"],
    }
    with ph_scoped_capture() as capture:
        capture(distinct_id=repo_config.repository, event=ROUTING_EVENT, properties=properties)


def _plan(
    client: StamphogGitHubClient, pr_obj: PullRequest, pr: Mapping[str, Any], *, claim: dict[str, Any]
) -> dict[str, Any]:
    """The claim with the routing decision and the GitHub writes it needs. Makes no GitHub write."""
    started = time.monotonic()
    repo_config = pr_obj.repo_config
    repository = repo_config.repository
    pinned_only = claim["scope"] == SCOPE_PINNED
    # Planned here so the model call can carry it, which links the run log row to its LLM trace.
    run_id = str(uuid7())
    fork = is_fork(pr, repository)
    files = [ChangedFile.from_github(entry) for entry in client.get_pr_files(repository, pr_obj.pr_number)]
    changed_files = pr.get("changed_files")
    # GitHub's file list stops at a page cap, and a pull request reports its own file count.
    files_truncated = isinstance(changed_files, int) and len(files) < changed_files
    if files_truncated:
        logger.warning(
            "stamphog_reviewer_routing_files_truncated",
            repo=repository,
            pr_number=pr_obj.pr_number,
            listed=len(files),
            changed_files=changed_files,
        )
    ownership = _resolve_owners(client, repository, files)
    candidates = find_candidates(files, ownership.resolutions)

    model = GatewayCutModel(
        team_id=repo_config.team_id,
        connected_by_user_id=repo_config.connected_by_user_id,
        attribution={
            "stamphog_runtime": "hosted",
            "stamphog_team_id": repo_config.team_id,
            "stamphog_step": "reviewer_routing",
            "stamphog_repo": repository,
            "stamphog_pr_number": pr_obj.pr_number,
            "stamphog_routing_run_id": run_id,
        },
    )
    if pinned_only:
        decision = keep_pinned(candidates)
        already = set(claim.get(REQUESTED_OWNERS) or [])
        # An approval of a later head requests only the pinned owners that no routing requested yet.
        to_request = [candidate for candidate in decision.kept if candidate.owner not in already]
    else:
        decision = decide_cuts(
            candidates=candidates,
            title=str(pr.get("title") or ""),
            description=str(pr.get("body") or ""),
            is_fork=fork,
            call_model=model,
            files_truncated=files_truncated,
        )
        to_request = list(decision.kept)
    requests = _plan_requests(to_request, fork=fork, labels_by_team=fork_labels(repo_config))
    planned_at = datetime.now(UTC).isoformat()
    return {
        **claim,
        "fork": fork,
        "candidates": [
            _candidate_record(
                candidate,
                decision,
                request_owners={owner.owner for owner in to_request},
                labeled_teams=set(requests.labeled_teams),
            )
            for candidate in candidates
        ],
        "kept": [candidate.owner for candidate in decision.kept],
        "cut": [{"owner": cut.candidate.owner, "reason": cut.reason} for cut in decision.cut],
        "run_id": run_id,
        "llm_skipped": decision.llm_skipped.value if decision.llm_skipped else None,
        "model": CUT_MODEL if model.sent_request else None,
        "additions_resolved": ownership.additions_resolved,
        "owners_sha": ownership.owners_sha,
        "files_truncated": files_truncated,
        "request_owners": [candidate.owner for candidate in to_request],
        "requested_teams": requests.teams,
        "requested_users": requests.users,
        "labeled_teams": requests.labeled_teams,
        "labels": requests.labels,
        "pending_comment": _comment_body(decision, repository),
        "input_tokens": model.usage.input_tokens if model.usage else 0,
        "output_tokens": model.usage.output_tokens if model.usage else 0,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "planned_at": planned_at,
        "routed_at": planned_at,
    }


def _record_run(pr_obj: PullRequest, record: dict[str, Any]) -> None:
    # The log is a record, not part of routing: it runs after the requests are saved as made, and a failed
    # write only logs, so it never makes the task retry and request again.
    try:
        record_routing_run(pr_obj, record)
    except Exception:
        logger.exception("stamphog_reviewer_routing_run_log_failed", pr_number=pr_obj.pr_number)


def _request_and_comment(client: StamphogGitHubClient, pr_obj: PullRequest, plan: dict[str, Any]) -> None:
    """Make the GitHub writes of a saved plan, then finish the comment."""
    repo_config = pr_obj.repo_config
    repository = repo_config.repository
    labels_refused = bool(plan["labels"]) and not client.add_pr_labels(repository, pr_obj.pr_number, plan["labels"])
    refused = client.request_reviewers(
        repository, pr_obj.pr_number, users=plan["requested_users"], teams=plan["requested_teams"]
    )
    if labels_refused:
        # Those fork teams got neither a label nor a review request.
        refused = [*refused, *plan["labeled_teams"]]
    if refused:
        logger.info("stamphog_reviewer_routing_refused", repo=repository, pr_number=pr_obj.pr_number, refused=refused)

    requested = {key: value for key, value in plan.items() if key != "previous"}
    requested["status"] = STATUS_REQUESTED
    requested["refused"] = refused
    requested[REQUESTED_OWNERS] = sorted({*(plan.get(REQUESTED_OWNERS) or []), *plan["request_owners"]})
    if plan["scope"] == SCOPE_PINNED:
        # A pinned routing from partial data must not stop the safety net, which routes this head in full.
        if not pinned_on_partial_data(plan):
            requested.update({PINNED_ROUTED_HEAD: plan["head_sha"], "pinned_routed_at": plan["routed_at"]})
    else:
        requested.update({FULL_ROUTED_HEAD: plan["head_sha"], "full_routed_at": plan["routed_at"]})
    if not _save_claimed(pr_obj, requested):
        return
    _record_run(pr_obj, requested)
    _capture(repo_config, requested)
    finish_comment(client, pr_obj, requested)


def resume_own_claim(client: StamphogGitHubClient, pr_obj: PullRequest, record: dict[str, Any]) -> bool:
    """Continue an own claim from its last saved step. False when the claim saved no plan yet."""
    if record.get("status") == STATUS_REQUESTED:
        # The requests went out: finish the comment, request nobody again.
        finish_comment(client, pr_obj, record)
        return True
    if record.get("planned_at"):
        # The plan is saved, so the retry makes its GitHub writes without a second model call.
        _request_and_comment(client, pr_obj, record)
        return True
    return False


def route_claimed(
    client: StamphogGitHubClient, pr_obj: PullRequest, pr: Mapping[str, Any], *, claim: dict[str, Any]
) -> None:
    """Plan under ``claim``, save the plan, then request reviews and comment.

    The claim's `scope` decides the run: `full` asks the cut step, `pinned` requests only the owners
    of sensitive and new paths, with no model call.
    """
    plan = _plan(client, pr_obj, pr, claim=claim)
    if not _save_claimed(pr_obj, plan):
        return
    _request_and_comment(client, pr_obj, plan)
