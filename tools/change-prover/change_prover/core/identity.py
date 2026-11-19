"""Which pull request a head may be proved for, and the handover between the identify and prove jobs."""

from __future__ import annotations

import re
from typing import Any

from change_prover.core.policy import ALLOWED_AUTHOR_IDS, Refused

COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
PULL_REQUEST_NUMBER = re.compile(r"[1-9][0-9]*")


def open_pulls_at_head(
    listed: list[dict[str, Any]], head_sha: str, base_branch: str, page_size: int
) -> list[dict[str, Any]]:
    """The open pull requests into the base branch whose head is this commit, from one page of the API."""
    if len(listed) >= page_size:
        raise Refused("more pull requests contain this commit than this proof reads")
    return [
        pr
        for pr in listed
        if pr["state"] == "open" and pr["base"]["ref"] == base_branch and pr["head"]["sha"] == head_sha
    ]


def pick_pull_request(pulls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one pull request by an allowed author, or None when there is none."""
    candidates = [pr for pr in pulls if pr["user"]["id"] in ALLOWED_AUTHOR_IDS]
    if not candidates:
        return None
    if len(candidates) > 1:
        raise Refused(f"{len(candidates)} pull requests by an allowed author have this head")
    return candidates[0]


def pick_any_pull_request(pulls: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one pull request at the head, by any author, or None when there is none.

    A revert proof is about the content of the change, so it admits every author.
    """
    if not pulls:
        return None
    if len(pulls) > 1:
        raise Refused(f"{len(pulls)} pull requests have this head")
    return pulls[0]


def check_head_repository(pr: dict[str, Any], repository: str) -> None:
    if (pr["head"].get("repo") or {}).get("full_name") != repository:
        raise Refused("the head branch is not in this repository")


def check_pusher(pr: dict[str, Any], pusher_id: int | None) -> None:
    if pusher_id != pr["user"]["id"]:
        raise Refused("the head commit was not pushed by the pull request author")


def check_handover(pull_request: str, merge_base: str) -> None:
    """Refuse the identification job's outputs unless every value has its exact shape."""
    if not PULL_REQUEST_NUMBER.fullmatch(pull_request):
        raise Refused("the pull request number is not a positive integer")
    if not COMMIT_SHA.fullmatch(merge_base):
        raise Refused("the merge base is not a commit id")


def check_reverted_handover(reverted: str) -> None:
    if not COMMIT_SHA.fullmatch(reverted):
        raise Refused("the reverted commit is not a commit id")
