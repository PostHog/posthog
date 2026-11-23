"""A hash of what people changed on a PR without pushing code.

A manual request for a head that stamphog already refused reviews it again only when this hash
differs from every review of that head: the author edited the title or the description, answered
in the discussion, or resolved a thread. Unlike ``decision_fingerprint``, the hash leaves out the
engine, the policy and everything else a deploy or CI moves, so only a person can change it.
"""

from __future__ import annotations

import json
import hashlib
from collections.abc import Mapping
from typing import Any

# Mirrors _TRUSTED_ASSOCIATIONS in packages/pr-approval-agent/github.py: the engine shows the reviewer
# discussion, reviews and inline comments only from these associations.
_PROMPT_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# Mirrors _BOT_MACHINE_USERS in packages/pr-approval-agent/github.py: org members that the engine treats as bots.
_MACHINE_USERS = frozenset({"posthog-bot"})

# Bump when the projection changes, so a hash from the old projection never matches a new one.
_VERSION = 1


def _is_bot(login: str, is_bot: bool) -> bool:
    return is_bot or "[bot]" in login or login.lower() in _MACHINE_USERS


def _from_person(user: Mapping[str, Any] | None, association: str | None) -> bool:
    """A trusted person wrote it. Bots are left out, stamphog's own verdicts included, so a bot posting
    again never earns another review."""
    user = user or {}
    login = user.get("login") or ""
    return not _is_bot(login, user.get("type") == "Bot") and association in _PROMPT_ASSOCIATIONS


def _reviews(reviews: list[dict]) -> list[dict]:
    # The engine drops a COMMENTED review without a body, so it is no evidence either.
    return [
        {
            "user": (review.get("user") or {}).get("login"),
            "state": review.get("state"),
            "body": review.get("body") or "",
        }
        for review in reviews
        if _from_person(review.get("user"), review.get("author_association"))
        and (review.get("state") != "COMMENTED" or (review.get("body") or "").strip())
    ]


def _discussion(comments: list[dict]) -> list[dict]:
    return [
        {"user": (comment.get("user") or {}).get("login"), "body": comment.get("body") or ""}
        for comment in comments
        if _from_person(comment.get("user"), comment.get("author_association"))
    ]


def _thread_comment_from_person(comment: Mapping[str, Any]) -> bool:
    login = comment.get("author") or ""
    return (
        not _is_bot(login, bool(comment.get("author_is_bot")))
        and comment.get("author_association") in _PROMPT_ASSOCIATIONS
    )


def _review_threads(threads: list[dict]) -> list[dict]:
    """The resolved threads, and the unresolved threads that a person wrote in, with those comments.

    The engine shows only unresolved threads, so a reply in a resolved thread is no evidence, but
    resolving or reopening a thread is, a bot's finding included. A thread that only a bot or an
    outsider wrote in counts once somebody resolves it, so a bot opening one moves nothing.
    """
    projected = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        location = {"path": thread.get("path"), "line": thread.get("line")}
        if thread.get("is_resolved"):
            projected.append({**location, "is_resolved": True})
            continue
        comments = [
            {"user": comment.get("author"), "body": comment.get("body") or ""}
            for comment in thread.get("comments") or []
            if isinstance(comment, dict) and _thread_comment_from_person(comment)
        ]
        if comments:
            projected.append({**location, "is_resolved": False, "comments": comments})
    return projected


def evidence_fingerprint(
    pr: Mapping[str, Any], *, reviews: list[dict], discussion: list[dict], review_threads: list[dict]
) -> str:
    """Hash the PR's title and body, and the reviews, discussion and review threads as GitHub returns them."""
    canonical = {
        "version": _VERSION,
        "title": pr.get("title") or "",
        "body": pr.get("body") or "",
        "reviews": _reviews([review for review in reviews if isinstance(review, dict)]),
        "discussion": _discussion([comment for comment in discussion if isinstance(comment, dict)]),
        "review_threads": _review_threads(review_threads),
    }
    encoded = json.dumps(canonical, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def stored_evidence_fingerprint(output: Mapping[str, Any]) -> str | None:
    """The hash of the evidence a run reviewed, from the context stored in its output. None when the
    run stored no PR, so nothing says what it saw."""
    pr = output.get("pr")
    if not isinstance(pr, dict):
        return None
    return evidence_fingerprint(
        pr,
        reviews=output.get("reviews") or [],
        discussion=output.get("discussion") or [],
        review_threads=output.get("review_threads") or [],
    )
