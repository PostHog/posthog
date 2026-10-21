from collections.abc import Mapping

from products.docs_freshness.backend.facade.contracts import PullRequestHead
from products.docs_freshness.backend.logic.impact_check import CHECKED_REPOSITORY, configured_settings
from products.docs_freshness.backend.temporal.client import start_check_pull_request_head_workflow

CHECKED_ACTIONS = frozenset({"opened", "reopened", "synchronize"})


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
