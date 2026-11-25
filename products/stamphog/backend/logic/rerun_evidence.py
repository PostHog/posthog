"""A hash of what people changed on a PR without pushing code.

A manual request for a head that stamphog already refused reviews it again only when this hash
differs from every review of that head: the author edited the title or the description, answered
in the discussion, or resolved a thread. Unlike ``decision_fingerprint``, the hash leaves out the
engine, the policy and everything else a deploy or CI moves, and it leaves out bots, stamphog's own
verdicts included. So only a person can change it.
"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from typing import Any

from products.stamphog.backend.logic.jsonb import without_nul

# Mirrors _TRUSTED_ASSOCIATIONS in packages/pr-approval-agent/github.py: the engine shows the reviewer
# discussion, reviews and inline comments only from these associations.
_PROMPT_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Mirrors _BOT_MACHINE_USERS in packages/pr-approval-agent/github.py: org members that the engine treats as bots.
_MACHINE_USERS = frozenset({"posthog-bot"})

# Bump when the projection changes, so a hash from the old projection never matches a new one.
_VERSION = 1


def _is_person(login: str, is_bot: bool, association: str | None) -> bool:
    # A deleted account comes back with no user, so it has no login.
    if not login or is_bot or "[bot]" in login or login.lower() in _MACHINE_USERS:
        return False
    return association in _PROMPT_ASSOCIATIONS


def _rest_items_by_people(items: list[Any]) -> list[dict]:
    """Reviews or issue comments as the REST API returns them, keeping only those a person wrote."""
    return [
        item
        for item in items
        if isinstance(item, dict)
        and _is_person(
            (item.get("user") or {}).get("login") or "",
            (item.get("user") or {}).get("type") == "Bot",
            item.get("author_association"),
        )
    ]


def _reviews(reviews: list[Any]) -> list[dict]:
    # The engine drops a COMMENTED review without a body, so it is no evidence either.
    return [
        {"user": review["user"].get("login"), "state": review.get("state"), "body": review.get("body") or ""}
        for review in _rest_items_by_people(reviews)
        if review.get("state") != "COMMENTED" or (review.get("body") or "").strip()
    ]


def _discussion(comments: list[Any]) -> list[dict]:
    return [
        {"user": comment["user"].get("login"), "body": comment.get("body") or ""}
        for comment in _rest_items_by_people(comments)
    ]


def _opening(thread: dict) -> dict:
    for comment in thread.get("comments") or []:
        if isinstance(comment, dict):
            return {"user": comment.get("author"), "body": comment.get("body") or ""}
    return {}


def _review_threads(threads: list[Any]) -> list[dict]:
    """The resolved threads, and the unresolved threads that a person wrote in, with those comments.

    The engine shows only unresolved threads, so a reply in a resolved thread is no evidence, but
    resolving or reopening a thread is, a bot's finding included. A thread that only a bot or an
    outsider wrote in counts once somebody resolves it, so a bot opening one moves nothing.

    The opening comment keeps two threads on one line apart, so resolving one instead of the other
    moves the hash. A GitHub thread id would do the same, but contexts stored before this hash existed
    hold no thread id, and their refusals would then never match unchanged evidence.
    """
    projected = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        location = {"path": thread.get("path"), "line": thread.get("line"), "opening": _opening(thread)}
        if thread.get("is_resolved"):
            projected.append({**location, "is_resolved": True})
            continue
        comments = [
            {"user": comment.get("author"), "body": comment.get("body") or ""}
            for comment in thread.get("comments") or []
            if isinstance(comment, dict)
            and _is_person(
                comment.get("author") or "", bool(comment.get("author_is_bot")), comment.get("author_association")
            )
        ]
        if comments:
            projected.append({**location, "is_resolved": False, "comments": comments})
    return projected


def evidence_fingerprint(
    pr: Mapping[str, Any],
    *,
    reviews: list[Any] | None,
    discussion: list[Any] | None,
    review_threads: list[Any] | None,
) -> str:
    """Hash the PR's title and body, and the reviews, discussion and review threads as the GitHub client
    returns them, whether read now or from a run's stored context.

    The stored context lost its NUL characters on the way into jsonb, so the hash drops them from both.
    """
    canonical = without_nul(
        {
            "version": _VERSION,
            "title": pr.get("title") or "",
            "body": pr.get("body") or "",
            "reviews": _reviews(reviews or []),
            "discussion": _discussion(discussion or []),
            "review_threads": _review_threads(review_threads or []),
        }
    )
    # ASCII escapes, because a comment can carry a lone surrogate that strict UTF-8 refuses to encode.
    encoded = json.dumps(canonical, sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()
