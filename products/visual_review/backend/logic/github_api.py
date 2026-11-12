"""GitHub HTTP access: integration lookup, rename-tolerant requests, file and PR reads."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from django.utils.dateparse import parse_datetime

import structlog

from posthog.egress.limiter.policies import Priority

if TYPE_CHECKING:
    import requests

    from posthog.models.integration import GitHubIntegration

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.integrations import IntegrationManager
from posthog.models.github_integration_base import GitHubIntegrationError

from ..models import Repo
from . import content_cache, errors

logger = structlog.get_logger(__name__)

# GitHub's own rate limit and a refusal by our shared egress budget (a non-CRITICAL call) both mean
# "ask again later". Readers let them through, where any other failure becomes None.
GITHUB_READ_REFUSED = (GitHubRateLimitError, GitHubEgressBudgetExhausted)


def _get_merge_base_sha(github: GitHubIntegration, repo_full_name: str, base: str, head: str) -> str | None:
    """Get the merge-base SHA between two refs via the GitHub Compare API."""
    try:
        response = github.api_request(
            "GET",
            f"/repos/{repo_full_name}/compare/{quote(base, safe='')}...{quote(head, safe='')}",
        )
    except GitHubIntegrationError:
        logger.warning("visual_review.merge_base_fetch_failed", repo=repo_full_name, base=base, head=head)
        return None

    if response.status_code != 200:
        logger.warning(
            "visual_review.merge_base_fetch_failed",
            repo=repo_full_name,
            base=base,
            head=head,
            status=response.status_code,
        )
        return None

    sha = response.json().get("merge_base_commit", {}).get("sha")
    if sha is None:
        logger.warning(
            "visual_review.merge_base_sha_missing_from_response",
            repo=repo_full_name,
            base=base,
            head=head,
        )
    return sha


def _get_default_branch(github: GitHubIntegration, repo_full_name: str) -> str:
    """The repo's default branch via the integration's cached verb. Falls back to 'master'."""
    try:
        return github.get_default_branch(repo_full_name)
    except GitHubRateLimitError:
        raise
    except Exception:
        logger.warning("visual_review.default_branch_fetch_failed", repo=repo_full_name)
        return "master"


def default_branch_name(repo: Repo, priority: Priority = Priority.CRITICAL) -> str | None:
    """The repo's default branch, or None when GitHub cannot say.

    Unlike `_get_default_branch`, there is no fallback name: a caller that decides on the answer
    must not treat a branch called master as the default during a GitHub outage. A rate limit
    or a refusal by the egress budget still raises, so a task can retry.
    """
    try:
        github = get_github_integration_for_repo(repo, priority)
        return github.get_default_branch(repo.repo_full_name)
    except GITHUB_READ_REFUSED:
        raise
    except Exception:
        logger.warning("visual_review.default_branch_fetch_failed", repo_id=str(repo.id))
        return None


def _read_json(log_event: str, send: Callable[[], requests.Response], **log_fields: object) -> Any:
    """The parsed body of a GitHub read, or None after a failed request or a status other than 200.

    A rate limit or a refusal by the egress budget propagates, so a caller can wait and ask again.
    """
    try:
        response = send()
    except GITHUB_READ_REFUSED:
        raise
    except Exception:
        logger.warning(log_event, **log_fields)
        return None
    if response.status_code != 200:
        logger.warning(log_event, status=response.status_code, **log_fields)
        return None
    return response.json()


def default_branch_head_sha(repo: Repo, priority: Priority = Priority.CRITICAL) -> str | None:
    """The commit the repo's default branch points at, or None when GitHub cannot say.

    Raises `GitHubIntegrationNotFoundError`, and `GitHubRateLimitError` or `GitHubEgressBudgetExhausted`,
    because a retry does not help the first and has to wait for the others.
    """
    github = get_github_integration_for_repo(repo, priority)

    def read_head() -> requests.Response:
        # Not `_get_default_branch`: its fallback name can point at a branch that is not the default,
        # and a commit from that branch would scope the lift wrongly.
        branch = github.get_default_branch(repo.repo_full_name)
        # One path segment, so a branch name with a slash does not split the ref.
        return github.api_request("GET", f"/repos/{repo.repo_full_name}/commits/{quote(branch, safe='')}")

    data = _read_json("visual_review.default_branch_head_fetch_failed", read_head, repo_id=str(repo.id))
    return None if data is None else data.get("sha")


def _is_ancestor(repo: Repo, ancestor_sha: str, head_sha: str, priority: Priority) -> bool | None:
    """Whether `ancestor_sha` is in the history of `head_sha`, or None when GitHub cannot tell.

    A rate limit or a refusal by the egress budget propagates, so a caller can wait and ask again.
    """
    try:
        github = get_github_integration_for_repo(repo, priority)
        merge_base = _get_merge_base_sha(github, repo.repo_full_name, ancestor_sha, head_sha)
    except errors.GitHubIntegrationNotFoundError:
        logger.warning("visual_review.commit_ancestry_unknown", repo_id=str(repo.id), ancestor=ancestor_sha)
        return None
    if merge_base is None:
        return None
    return merge_base == ancestor_sha


def commit_ancestry(
    repo: Repo, ancestor_sha: str, head_sha: str, priority: Priority = Priority.CRITICAL
) -> bool | None:
    """Whether `ancestor_sha` is in the history of `head_sha`, or None when GitHub cannot tell.

    Two commits never change their ancestry, so a known answer is cached and later calls for the
    same pair make no request. An unknown answer is not cached, so the next call asks again. A rate
    limit raises `GitHubRateLimitError` and a refusal by the egress budget raises
    `GitHubEgressBudgetExhausted`, so a caller on a retry path waits instead of failing for good.
    """
    if ancestor_sha == head_sha:
        return True
    return content_cache.load_by_hash(
        "commit_ancestry",
        f"{repo.id}:{ancestor_sha}..{head_sha}",
        lambda: _is_ancestor(repo, ancestor_sha, head_sha, priority),
    )


def commit_contains(repo: Repo, ancestor_sha: str, head_sha: str) -> bool:
    """Whether `ancestor_sha` is in the history of `head_sha`. False when GitHub cannot tell.

    A refused read also answers False, because the callers of this function do not retry.
    """
    try:
        return commit_ancestry(repo, ancestor_sha, head_sha) is True
    except GITHUB_READ_REFUSED:
        logger.warning("visual_review.commit_ancestry_unknown", repo_id=str(repo.id), ancestor=ancestor_sha)
        return False


_MERGE_QUEUE_BRANCH_RE = re.compile(r"^trunk-merge/pr-(?P<pr_number>\d+)/")


def is_merge_queue_branch(branch: str) -> bool:
    return _MERGE_QUEUE_BRANCH_RE.match(branch) is not None


def _verified_merge_queue_source_pr(
    github: GitHubIntegration, repo_full_name: str, branch: str, head_ref: str | None = None
) -> int | None:
    """Source PR number for a merge-queue branch, verified against GitHub.

    Merge-queue branches (``trunk-merge/pr-<n>/<uuid>``) are freshly
    minted per attempt, so tombstones recorded on the source PR would
    never apply — every queue attempt would re-heal the removed entries
    and fail the gate. Queue branches therefore also honor the source
    PR's tombstones.

    The branch name is client-supplied, though, so parsing it alone must
    not grant cross-PR tombstone inheritance: a caller with a write token
    could name a branch after an unrelated PR to inherit its approved
    removals. Require the claimed PR's head commit to be an ancestor of
    the queue branch — inheriting a PR's approvals then means actually
    testing that PR's code, which is exactly what Trunk's queue branches
    do (they merge the PR into the base branch). Fails closed to
    branch-only scoping.
    """
    match = _MERGE_QUEUE_BRANCH_RE.match(branch)
    if not match:
        return None
    pr_number = int(match.group("pr_number"))

    try:
        response = github.api_request("GET", f"/repos/{repo_full_name}/pulls/{pr_number}")
    except GitHubIntegrationError:
        logger.warning("visual_review.merge_queue_source_pr_fetch_failed", repo=repo_full_name, branch=branch)
        return None
    if response.status_code != 200:
        logger.warning(
            "visual_review.merge_queue_source_pr_fetch_failed",
            repo=repo_full_name,
            branch=branch,
            status=response.status_code,
        )
        return None

    pr_head_sha = (response.json().get("head") or {}).get("sha")
    if not pr_head_sha:
        return None

    # Compare against *head_ref* when the caller has the commit: the branch is
    # deleted as soon as its batch resolves, and a 404 here reads as "unverified"
    # and silently drops the inheritance this function exists to grant.
    if _get_merge_base_sha(github, repo_full_name, pr_head_sha, head_ref or branch) != pr_head_sha:
        logger.warning(
            "visual_review.merge_queue_source_pr_unverified",
            repo=repo_full_name,
            branch=branch,
            pr_number=pr_number,
            pr_head_sha=pr_head_sha,
        )
        return None

    return pr_number


def is_verified_merge_queue_run(repo: Repo, branch: str, commit_sha: str) -> bool:
    """Whether a run's merge queue branch really tests the pull request its name claims.

    The branch name is client-supplied, so a run only counts as a merge queue run once GitHub
    confirms that the claimed pull request's head is in the run's commit. False when GitHub cannot say.
    """
    try:
        github = get_github_integration_for_repo(repo)
        return _verified_merge_queue_source_pr(github, repo.repo_full_name, branch, head_ref=commit_sha) is not None
    except (errors.GitHubIntegrationNotFoundError, GitHubRateLimitError):
        logger.warning("visual_review.merge_queue_run_unverified", repo_id=str(repo.id), branch=branch)
        return False


def get_github_integration_for_repo(repo: Repo, priority: Priority = Priority.CRITICAL):
    """Get GitHub integration for the repo's team."""
    from posthog.models.integration import GitHubIntegration

    integration = IntegrationManager.github.oauth.find(repo.team_id)

    if not integration:
        raise errors.GitHubIntegrationNotFoundError(f"No GitHub integration found for team {repo.team_id}")

    return GitHubIntegration(integration, source="visual_review", priority=priority)


def _resolve_repo_by_id(github, repo_external_id: int) -> str | None:
    """
    Look up the current full_name of a repo by its numeric GitHub ID.

    Used to detect renames: GET /repositories/{id} always returns the
    latest full_name even if the repo was renamed or transferred.
    Returns None if the repo is inaccessible.
    """
    response = github.api_request("GET", f"/repositories/{repo_external_id}")
    if response.status_code == 200:
        return response.json().get("full_name")
    return None


def _github_api_request(
    method: str,
    repo: Repo,
    path: str,
    *,
    json: Mapping[str, object] | None = None,
    params: dict[str, str | int] | None = None,
    timeout: int = 10,
    priority: Priority = Priority.CRITICAL,
) -> requests.Response:
    """
    Make a GitHub API request, auto-resolving renamed repos on 404.

    If the request returns 404 and the repo has an external ID, looks up
    the current full_name via /repositories/{id}. If it changed, updates
    the stored repo_full_name and retries once.
    """
    segments = path.split("/")
    # `quote` leaves a dot segment as it is, and the HTTP client resolves it to another path, so refuse it.
    if any(segment in (".", "..") for segment in segments):
        raise ValueError(f"GitHub API path has a dot segment: {path!r}")
    # Quoting each segment keeps a `?` or `#` inside a value from starting a query or a fragment.
    safe_path = "/".join(quote(segment, safe="") for segment in segments)

    github = get_github_integration_for_repo(repo, priority)

    response = github.api_request(
        method, f"/repos/{repo.repo_full_name}/{safe_path}", json_body=json, params=params, timeout=timeout
    )

    if response.status_code == 404 and repo.repo_external_id:
        new_full_name = _resolve_repo_by_id(github, repo.repo_external_id)
        if new_full_name and new_full_name != repo.repo_full_name:
            logger.info(
                "visual_review.repo_renamed",
                repo_id=str(repo.id),
                old_name=repo.repo_full_name,
                new_name=new_full_name,
            )
            repo.repo_full_name = new_full_name
            repo.save(update_fields=["repo_full_name"])

            response = github.api_request(
                method, f"/repos/{new_full_name}/{safe_path}", json_body=json, params=params, timeout=timeout
            )

    return response


def _get_pr_info(github, repo_full_name: str, pr_number: int) -> dict:
    """
    Fetch PR info from GitHub.

    Returns dict with head_ref (branch), head_sha, and whether the PR is still open.
    """
    response = github.api_request("GET", f"/repos/{repo_full_name}/pulls/{pr_number}")

    if response.status_code != 200:
        raise errors.GitHubCommitError(f"Failed to fetch PR info: {response.status_code} {response.text}")

    pr_data = response.json()
    return {
        "head_ref": pr_data["head"]["ref"],
        "head_sha": pr_data["head"]["sha"],
        "open": pr_data.get("state", "open") == "open" and not pr_data.get("merged", False),
    }


@frozen
class PullRequestState:
    """What GitHub says about a pull request, as far as a merge check needs it."""

    state: str  # "open" or "closed"
    merged: bool
    merge_commit_sha: str | None
    base_ref: str
    head_sha: str | None
    merged_at: datetime | None = None


def pull_request_state(repo: Repo, pr_number: int, priority: Priority = Priority.CRITICAL) -> PullRequestState | None:
    """The pull request's merge state, or None when GitHub cannot say."""
    data = _read_json(
        "visual_review.pull_request_state_fetch_failed",
        lambda: get_github_integration_for_repo(repo, priority).api_request(
            "GET", f"/repos/{repo.repo_full_name}/pulls/{pr_number}"
        ),
        repo_id=str(repo.id),
        pr_number=pr_number,
    )
    if data is None:
        return None
    return PullRequestState(
        state=data.get("state") or "",
        merged=bool(data.get("merged")),
        merge_commit_sha=data.get("merge_commit_sha"),
        base_ref=(data.get("base") or {}).get("ref") or "",
        head_sha=(data.get("head") or {}).get("sha"),
        merged_at=parse_datetime(data["merged_at"]) if data.get("merged_at") else None,
    )


@frozen
class MergedPullRequest:
    number: int
    base_ref: str
    head_sha: str | None


def merged_pull_requests_for_commit(
    repo: Repo, sha: str, priority: Priority = Priority.CRITICAL
) -> list[MergedPullRequest] | None:
    """The pull requests whose merge produced `sha`, or None when GitHub cannot say."""
    items = _read_json(
        "visual_review.commit_pull_requests_fetch_failed",
        lambda: _github_api_request("GET", repo, f"commits/{sha}/pulls", priority=priority),
        repo_id=str(repo.id),
        sha=sha,
    )
    if items is None:
        return None
    # The list also holds open pull requests that merely contain the commit, and the list items
    # carry `merged_at` instead of the `merged` flag of the single pull request read.
    return [
        MergedPullRequest(
            number=item["number"],
            base_ref=(item.get("base") or {}).get("ref") or "",
            head_sha=(item.get("head") or {}).get("sha"),
        )
        for item in items
        if item.get("merged_at") and item.get("merge_commit_sha") == sha
    ]


# Ten pages of the compare endpoint. Past that the default branch went unwatched for long enough
# that an operator re-seeds the ledger, and one call must not spend the rate limit on a long walk.
MAX_COMPARE_COMMITS = 1000
_COMPARE_PAGE_SIZE = 100


@frozen
class ComparedCommit:
    sha: str
    parent_shas: tuple[str, ...]
    subject: str


@frozen
class Comparison:
    merge_base_sha: str | None
    commits: tuple[ComparedCommit, ...]
    # False when GitHub reports more commits than were read.
    complete: bool


def _compared_commit(item: dict) -> ComparedCommit:
    return ComparedCommit(
        sha=item["sha"],
        parent_shas=tuple(parent["sha"] for parent in item["parents"]),
        subject=item["commit"]["message"].split("\n", 1)[0],
    )


def compare_commits(repo: Repo, base: str, head: str, priority: Priority = Priority.CRITICAL) -> Comparison | None:
    """The merge-base of two commits and the commits `head` has that `base` does not.

    None when GitHub cannot say. GitHub sorts the commits by date, not by ancestry, so a caller
    that needs the order follows the parent links.
    """
    commits: list[ComparedCommit] = []
    merge_base_sha: str | None = None
    total_commits = 0
    page = 1
    while len(commits) < MAX_COMPARE_COMMITS:
        data = _read_json(
            "visual_review.compare_fetch_failed",
            partial(
                _github_api_request,
                "GET",
                repo,
                f"compare/{base}...{head}",
                params={"per_page": _COMPARE_PAGE_SIZE, "page": page},
                priority=priority,
            ),
            repo_id=str(repo.id),
            base=base,
            head=head,
        )
        if data is None:
            return None
        merge_base_sha = (data.get("merge_base_commit") or {}).get("sha")
        total_commits = data.get("total_commits") or 0
        page_commits = [_compared_commit(item) for item in data.get("commits") or []]
        commits.extend(page_commits)
        if not page_commits or len(commits) >= total_commits:
            break
        page += 1
    return Comparison(
        merge_base_sha=merge_base_sha,
        commits=tuple(commits),
        complete=len(commits) >= total_commits,
    )


# A larger baseline file is parsed without caching, so one repository cannot fill the shared cache
# with large parsed files.
_MAX_CACHED_BASELINE_BYTES = 2 * 1024 * 1024


def _parse_baseline_file(text: str) -> dict[str, dict]:
    """Identifier to its signed entry, for a version 1 baseline file. Empty for anything else."""
    import yaml

    parsed = yaml.safe_load(text)
    if not parsed or parsed.get("version") != 1:
        return {}

    raw_snapshots = parsed.get("snapshots", {})

    normalized: dict[str, dict] = {}
    for identifier, value in raw_snapshots.items():
        if isinstance(value, dict) and "hash" in value:
            normalized[identifier] = value
    return normalized


def _fetch_baseline_file(
    github, repo_full_name: str, file_path: str, branch: str
) -> tuple[dict[str, dict], str | None]:
    """
    Fetch current baseline file content from GitHub.

    Returns ``(snapshots_dict, file_sha)``. Snapshots dict maps
    identifier to ``{hash: "v1.kid.hash.tag"}`` (the signed format).
    If the file doesn't exist, returns ``({}, None)``.

    The file is parsed once per blob SHA. Every run reads it at least once, and most reads name a
    blob that an earlier run already downloaded, because the file only changes when a baseline
    commit lands. The small contents call still runs every time, since a branch ref can move.
    """
    try:
        entry = github.get_file_entry(repo_full_name, file_path, ref=branch)
        if entry is None:
            return {}, None

        def read_and_parse() -> dict[str, dict]:
            text = entry["content"]
            if text is None:
                text = github.get_blob_text(repo_full_name, entry["sha"], entry["size"])
            return _parse_baseline_file(text)

        if entry["size"] > _MAX_CACHED_BASELINE_BYTES:
            baselines: dict[str, dict] | None = read_and_parse()
        else:
            baselines = content_cache.load_by_hash("baseline_file", entry["sha"], read_and_parse)
    except GitHubRateLimitError:
        raise
    except GitHubIntegrationError as e:
        raise errors.GitHubCommitError(f"Failed to fetch baseline file: {e}") from e

    return baselines or {}, entry["sha"]
