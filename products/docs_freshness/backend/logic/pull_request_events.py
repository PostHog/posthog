import re
from collections.abc import Mapping

from products.docs_freshness.backend.facade.contracts import LandedCommit, PullRequestHead
from products.docs_freshness.backend.logic.impact_check import CHECKED_REPOSITORY, configured_settings
from products.docs_freshness.backend.temporal.client import (
    start_check_landed_commit_workflows,
    start_check_pull_request_head_workflow,
)

CHECKED_ACTIONS = frozenset({"opened", "reopened", "synchronize"})
LANDING_BRANCH_REF = "refs/heads/master"

_PULL_REQUEST_NUMBER_SUFFIX_RE = re.compile(r"\(#([1-9][0-9]*)\)$")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def pull_request_head_from_payload(payload: Mapping[str, object]) -> PullRequestHead | None:
    if payload.get("action") not in CHECKED_ACTIONS:
        return None
    pull_request = _mapping(payload.get("pull_request"))
    if pull_request.get("state") != "open":
        return None
    repository = _mapping(payload.get("repository")).get("full_name")
    pr_number = pull_request.get("number")
    head_sha = _mapping(pull_request.get("head")).get("sha")
    if not isinstance(repository, str) or repository.lower() != CHECKED_REPOSITORY:
        return None
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or not isinstance(head_sha, str):
        return None
    return PullRequestHead(repository=repository, pr_number=pr_number, head_sha=head_sha)


def accept_pull_request_event(payload: Mapping[str, object]) -> None:
    if configured_settings() is None:
        return
    head = pull_request_head_from_payload(payload)
    if head is None:
        return
    start_check_pull_request_head_workflow(head)


def landed_commits_from_push(payload: Mapping[str, object]) -> list[LandedCommit]:
    if payload.get("ref") != LANDING_BRANCH_REF or payload.get("deleted"):
        return []
    repository = _mapping(payload.get("repository")).get("full_name")
    commits = payload.get("commits")
    if not isinstance(repository, str) or repository.lower() != CHECKED_REPOSITORY or not isinstance(commits, list):
        return []
    landed_commits = [_landed_commit(repository, _mapping(commit)) for commit in commits]
    return [commit for commit in landed_commits if commit is not None]


def _landed_commit(repository: str, commit: Mapping[str, object]) -> LandedCommit | None:
    merge_sha = commit.get("id")
    message = commit.get("message")
    if not isinstance(merge_sha, str) or not isinstance(message, str):
        return None
    subject = message.split("\n", 1)[0].rstrip()
    pull_request_number = _PULL_REQUEST_NUMBER_SUFFIX_RE.search(subject)
    if pull_request_number is None:
        return None
    return LandedCommit(repository=repository, pr_number=int(pull_request_number.group(1)), merge_sha=merge_sha)


def accept_push_event(payload: Mapping[str, object]) -> None:
    if configured_settings() is None:
        return
    landed_commits = landed_commits_from_push(payload)
    if not landed_commits:
        return
    start_check_landed_commit_workflows(landed_commits)
