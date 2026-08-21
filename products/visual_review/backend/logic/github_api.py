"""GitHub HTTP access: integration lookup, rename-tolerant requests, file and PR reads."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import quote

import structlog

if TYPE_CHECKING:
    import requests

    from posthog.models.integration import GitHubIntegration

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationError

from ..models import Repo
from . import errors

logger = structlog.get_logger(__name__)


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


_MERGE_QUEUE_BRANCH_RE = re.compile(r"^trunk-merge/pr-(?P<pr_number>\d+)/")


def _verified_merge_queue_source_pr(github: GitHubIntegration, repo_full_name: str, branch: str) -> int | None:
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

    if _get_merge_base_sha(github, repo_full_name, pr_head_sha, branch) != pr_head_sha:
        logger.warning(
            "visual_review.merge_queue_source_pr_unverified",
            repo=repo_full_name,
            branch=branch,
            pr_number=pr_number,
            pr_head_sha=pr_head_sha,
        )
        return None

    return pr_number


def get_github_integration_for_repo(repo: Repo):
    """Get GitHub integration for the repo's team."""
    from posthog.models.integration import GitHubIntegration, Integration

    integration = Integration.objects.filter(team_id=repo.team_id, kind="github").first()

    if not integration:
        raise errors.GitHubIntegrationNotFoundError(f"No GitHub integration found for team {repo.team_id}")

    return GitHubIntegration(integration, source="visual_review")


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
    timeout: int = 10,
) -> requests.Response:
    """
    Make a GitHub API request, auto-resolving renamed repos on 404.

    If the request returns 404 and the repo has an external ID, looks up
    the current full_name via /repositories/{id}. If it changed, updates
    the stored repo_full_name and retries once.
    """
    # Prevent path traversal — each segment must be safe
    safe_path = "/".join(quote(segment, safe="") for segment in path.split("/"))

    github = get_github_integration_for_repo(repo)

    response = github.api_request(method, f"/repos/{repo.repo_full_name}/{safe_path}", json_body=json, timeout=timeout)

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
                method, f"/repos/{new_full_name}/{safe_path}", json_body=json, timeout=timeout
            )

    return response


def _get_pr_info(github, repo_full_name: str, pr_number: int) -> dict:
    """
    Fetch PR info from GitHub.

    Returns dict with head_ref (branch) and head_sha.
    """
    response = github.api_request("GET", f"/repos/{repo_full_name}/pulls/{pr_number}")

    if response.status_code != 200:
        raise errors.GitHubCommitError(f"Failed to fetch PR info: {response.status_code} {response.text}")

    pr_data = response.json()
    return {
        "head_ref": pr_data["head"]["ref"],
        "head_sha": pr_data["head"]["sha"],
    }


def _fetch_baseline_file(
    github, repo_full_name: str, file_path: str, branch: str
) -> tuple[dict[str, dict], str | None]:
    """
    Fetch current baseline file content from GitHub.

    Returns ``(snapshots_dict, file_sha)``. Snapshots dict maps
    identifier to ``{hash: "v1.kid.hash.tag"}`` (the signed format).
    If the file doesn't exist, returns ``({}, None)``.
    """
    import yaml

    try:
        result = github.get_file_contents(repo_full_name, file_path, ref=branch)
    except GitHubRateLimitError:
        raise
    except GitHubIntegrationError as e:
        raise errors.GitHubCommitError(f"Failed to fetch baseline file: {e}") from e

    if result is None:
        return {}, None

    file_sha = result["sha"]

    parsed = yaml.safe_load(result["content"])
    if not parsed or parsed.get("version") != 1:
        return {}, file_sha

    raw_snapshots = parsed.get("snapshots", {})

    normalized: dict[str, dict] = {}
    for identifier, value in raw_snapshots.items():
        if isinstance(value, dict) and "hash" in value:
            normalized[identifier] = value
    return normalized, file_sha
