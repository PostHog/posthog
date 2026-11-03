"""One reviewer routing run: owners of the changed code, the cut step, the review requests and the comment.

The repo's `routing_mode` decides when a run happens. ALWAYS routes when a pull request opens or
becomes ready. FALLBACK waits for stamphog's verdict on the head when stamphog will review it: an
approval requests only the pinned owners, any other outcome routes in full. Routing runs for bot
and fork pull requests too, like the CI assigner it replaces. Ownership is read from the default
branch, never from the pull request head, so a pull request cannot name its own reviewers.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from django.db import router

import structlog
from owners_yaml import OwnersResolver, Resolution

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.ownership.github_files import AuthenticatedRepoFiles, AuthenticatedRepoTree, GitHubFilesFetcher
from posthog.ph_client import ph_scoped_capture

from products.stamphog.backend.facade.enums import RoutingMode
from products.stamphog.backend.logic.github_client import StamphogGitHubClient
from products.stamphog.backend.logic.routing.candidates import (
    ADDED_FILE_STATUSES,
    ChangedFile,
    OwnerCandidate,
    OwnerKind,
    find_candidates,
    is_excluded,
    paths_to_resolve,
)
from products.stamphog.backend.logic.routing.comment import (
    ROUTING_COMMENT_MARKER,
    render_approved_routing_comment,
    render_routing_comment,
)
from products.stamphog.backend.logic.routing.cut import (
    CUT_MODEL,
    LlmSkipReason,
    RoutingDecision,
    decide_cuts,
    keep_pinned,
)
from products.stamphog.backend.logic.routing.model import GatewayCutModel
from products.stamphog.backend.logic.scrubbing import neutralize_active_markdown, scrub_credentials
from products.stamphog.backend.models import PullRequest, StamphogRepoConfig

logger = structlog.get_logger(__name__)

ROUTING_EVENT = "stamphog_reviewer_routing_completed"
# FALLBACK only: the head waits for stamphog's verdict or for the safety net, whichever comes first.
STATUS_WAITING = "waiting"
# FALLBACK only: a verdict or the safety net claimed the waiting head, and its routing is running.
STATUS_ROUTING = "routing"
# A record stays REQUESTED between the review requests and the comment, so a retry finishes the
# comment without requesting anybody a second time.
STATUS_REQUESTED = "requested"
STATUS_DONE = "done"

TRIGGER_SAFETY_NET = "safety_net"

# PR-level marks, carried over every later record of the pull request. FALLBACK routes in full at
# most once per pull request, and an approval requests the pinned owners at most once.
FULL_ROUTED_HEAD = "full_routed_head"
PINNED_ROUTED_HEAD = "pinned_routed_head"
# Whether the latest finished routing left a routing comment on the pull request. Only then does a
# routing that writes no comment page through the comments to delete it.
COMMENT_POSTED = "comment_posted"
_PR_MARK_KEYS = (FULL_ROUTED_HEAD, "full_routed_at", PINNED_ROUTED_HEAD, "pinned_routed_at", COMMENT_POSTED)
# The skip values of a run that called the model: it answered (None) or the call failed (NO_ANSWER).
_CALLED_MODEL_SKIPS = frozenset({None, LlmSkipReason.NO_ANSWER})


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


def _save_routing(pr_obj: PullRequest, record: dict[str, Any]) -> None:
    PullRequest.objects.for_team(pr_obj.team_id).using(router.db_for_write(PullRequest)).filter(id=pr_obj.id).update(
        routing=record
    )


def _pr_marks(previous: Mapping[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {}
    return {key: previous[key] for key in _PR_MARK_KEYS if key in previous}


def _replace_routing(pr_obj: PullRequest, *, expected: Mapping[str, Any] | None, record: dict[str, Any]) -> bool:
    """Write ``record`` only while the stored record still equals ``expected``.

    A verdict and a safety net can fire at the same moment. Only one of them wins the compare and
    swap, so the pull request gets one set of review requests.
    """
    rows = PullRequest.objects.for_team(pr_obj.team_id).using(router.db_for_write(PullRequest)).filter(id=pr_obj.id)
    rows = rows.filter(routing__isnull=True) if expected is None else rows.filter(routing=expected)
    return rows.update(routing=record) == 1


def _fallback_record(expected: Mapping[str, Any] | None, *, head_sha: str, trigger: str, status: str) -> dict[str, Any]:
    return {
        **_pr_marks(expected),
        "head_sha": head_sha,
        "mode": RoutingMode.FALLBACK.value,
        "trigger": trigger,
        "status": status,
    }


def save_waiting(pr_obj: PullRequest, *, expected: Mapping[str, Any] | None, head_sha: str, trigger: str) -> bool:
    record = _fallback_record(expected, head_sha=head_sha, trigger=trigger, status=STATUS_WAITING)
    record["waiting_since"] = datetime.now(UTC).isoformat()
    return _replace_routing(pr_obj, expected=expected, record=record)


def claim_routing(
    pr_obj: PullRequest, *, expected: Mapping[str, Any] | None, head_sha: str, trigger: str, claimed_by: str
) -> dict[str, Any] | None:
    """Claim the head for one task. Returns the claim, or None when another task changed the record first.

    ``claimed_by`` is the Celery task id, which a retry of the same task keeps, so a retry knows its own claim.
    """
    claim = _fallback_record(expected, head_sha=head_sha, trigger=trigger, status=STATUS_ROUTING)
    claim["claimed_by"] = claimed_by
    return claim if _replace_routing(pr_obj, expected=expected, record=claim) else None


class _OwnersReader:
    """Resolves owners at the default branch with Stamphog's own installation token."""

    def __init__(self, client: StamphogGitHubClient, repository: str) -> None:
        self._repository = repository
        self._fetcher = GitHubFilesFetcher.from_token(
            client.installation_token(),
            installation_id=client.installation_id,
            refresh=client.refresh_installation_token,
            # The author waits on the review requests.
            priority=Priority.NORMAL,
        )

    def resolve(self, paths: list[str]) -> dict[str, Resolution]:
        # The run requests reviewers once and never corrects them later, so it reads the head of
        # this run rather than a head another read cached a minute ago.
        files = AuthenticatedRepoFiles(self._repository, self._fetcher, fresh_head=True)
        return OwnersResolver(source=files).map(paths)

    def resolve_additions(self, paths: list[str]) -> dict[str, Resolution]:
        tree = AuthenticatedRepoTree(self._repository, self._fetcher, fresh_head=True)
        tree.prefetch_kinds(paths)
        return OwnersResolver(source=tree).map(paths)


def _resolve_owners(reader: _OwnersReader, files: Sequence[ChangedFile]) -> tuple[dict[str, Resolution], bool]:
    """Every path's resolution, and whether the owners of additions are part of it.

    The owners of additions are an extra. A failure there routes without their pins rather than
    failing the run; a failure of the plain ownership read raises.
    """
    resolutions = reader.resolve(paths_to_resolve(files))
    added = list(
        dict.fromkeys(file.path for file in files if file.status in ADDED_FILE_STATUSES and not is_excluded(file.path))
    )
    if not added:
        return resolutions, True
    try:
        resolutions.update(reader.resolve_additions(added))
    except Exception:
        logger.warning("stamphog_reviewer_routing_additions_unavailable", exc_info=True)
        return resolutions, False
    return resolutions, True


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


def _candidate_record(candidate: OwnerCandidate) -> dict[str, Any]:
    return {
        "owner": candidate.owner,
        "kind": candidate.kind.value,
        "lines": candidate.lines,
        "file_count": len(candidate.files),
        "pins": sorted(({"reason": pin.reason.value, "path": pin.path} for pin in candidate.pins), key=str),
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
    done["status"] = STATUS_DONE
    done[COMMENT_POSTED] = posted
    _save_routing(pr_obj, done)


def _capture(
    repo_config: StamphogRepoConfig, record: dict[str, Any], *, latency_ms: int, model: GatewayCutModel
) -> None:
    # Counts only: no title, path or reason leaves for analytics.
    properties: dict[str, Any] = {
        "stamphog_repo": repo_config.repository,
        "stamphog_team_id": repo_config.team_id,
        "stamphog_routing_mode": record["mode"],
        "stamphog_routing_trigger": record["trigger"],
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
        "stamphog_routing_latency_ms": latency_ms,
        "stamphog_routing_input_tokens": model.usage.input_tokens if model.usage else 0,
        "stamphog_routing_output_tokens": model.usage.output_tokens if model.usage else 0,
    }
    with ph_scoped_capture() as capture:
        capture(distinct_id=repo_config.repository, event=ROUTING_EVENT, properties=properties)


def route_reviewers(
    client: StamphogGitHubClient,
    pr_obj: PullRequest,
    pr: Mapping[str, Any],
    *,
    trigger: str,
    mode: RoutingMode,
    pinned_only: bool = False,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Request reviews from the owners the cut step keeps, then comment on the cut ones.

    ``pinned_only`` is for a head that stamphog approved: it requests only the owners of sensitive
    and new paths, with no model call. ``previous`` is the stored record this run replaces: its
    PR-level marks and its claim carry over. The record is saved between the requests and the comment,
    so a retry after a failed comment finishes the comment without requesting anybody twice.
    Returns the final record.
    """
    started = time.monotonic()
    repo_config = pr_obj.repo_config
    repository = repo_config.repository
    fork = is_fork(pr, repository)
    files = [ChangedFile.from_github(entry) for entry in client.get_pr_files(repository, pr_obj.pr_number)]
    resolutions, additions_resolved = _resolve_owners(_OwnersReader(client, repository), files)
    candidates = find_candidates(files, resolutions)

    model = GatewayCutModel(
        team_id=repo_config.team_id,
        connected_by_user_id=repo_config.connected_by_user_id,
        attribution={
            "stamphog_runtime": "hosted",
            "stamphog_team_id": repo_config.team_id,
            "stamphog_step": "reviewer_routing",
        },
    )
    if pinned_only:
        decision = keep_pinned(candidates)
    else:
        decision = decide_cuts(
            candidates=candidates,
            title=str(pr.get("title") or ""),
            description=str(pr.get("body") or ""),
            is_fork=fork,
            call_model=model,
        )

    requests = _plan_requests(decision.kept, fork=fork, labels_by_team=fork_labels(repo_config))
    if requests.labels:
        client.add_pr_labels(repository, pr_obj.pr_number, requests.labels)
    refused = client.request_reviewers(repository, pr_obj.pr_number, users=requests.users, teams=requests.teams)
    if refused:
        logger.info("stamphog_reviewer_routing_refused", repo=repository, pr_number=pr_obj.pr_number, refused=refused)

    head_sha = (pr.get("head") or {}).get("sha") or ""
    routed_at = datetime.now(UTC).isoformat()
    marks = _pr_marks(previous)
    if pinned_only:
        marks.update({PINNED_ROUTED_HEAD: head_sha, "pinned_routed_at": routed_at})
    else:
        marks.update({FULL_ROUTED_HEAD: head_sha, "full_routed_at": routed_at})
    record: dict[str, Any] = {
        **marks,
        "head_sha": head_sha,
        "mode": mode.value,
        "trigger": trigger,
        "status": STATUS_REQUESTED,
        "fork": fork,
        "candidates": [_candidate_record(candidate) for candidate in candidates],
        "kept": [candidate.owner for candidate in decision.kept],
        "cut": [{"owner": cut.candidate.owner, "reason": cut.reason} for cut in decision.cut],
        "llm_skipped": decision.llm_skipped.value if decision.llm_skipped else None,
        "model": CUT_MODEL if decision.llm_skipped in _CALLED_MODEL_SKIPS else None,
        "additions_resolved": additions_resolved,
        "requested_teams": requests.teams,
        "requested_users": requests.users,
        "labeled_teams": requests.labeled_teams,
        "refused": refused,
        "routed_at": routed_at,
        "pending_comment": _comment_body(decision, repository),
    }
    if previous is not None and "claimed_by" in previous:
        record["claimed_by"] = previous["claimed_by"]
    _save_routing(pr_obj, record)
    _capture(repo_config, record, latency_ms=int((time.monotonic() - started) * 1000), model=model)
    finish_comment(client, pr_obj, record)
    return record
