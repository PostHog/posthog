"""Turns a verified ``issue_comment`` delivery into a command request, or drops it.

This runs inside the webhook request, so it reads only the payload: no database, no GitHub API.
Every check here is a cheap filter that drops noise before a task is queued. None of them is the
authority on who may run a command. The task re-checks the commenter against GitHub and PostHog
before anything runs (see ``dispatch.py``).
"""

import re
from collections.abc import Mapping
from typing import Literal

from posthog.dataclasses import frozen

from .parsing import AmbiguousCommand, ParsedCommand, parse_command

# GitHub's `author_association` for people with a standing relationship to the repository.
# Outside contributors never get past this filter, so they cannot spend the task queue.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# The name goes into GitHub API paths, so it must be exactly `owner/name`.
REPOSITORY_NAME_RE = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}")

DropReason = Literal[
    "not_created",
    "not_pull_request",
    "no_command",
    "bot_author",
    "app_authored",
    "untrusted_association",
    "malformed",
]


@frozen
class CommentCommandRequest:
    """Everything the task needs, copied out of the payload as plain values.

    It holds identifiers and the commenter's own command line only. The pull request title, body
    and other comments are not carried: a handler that needs them reads them from GitHub itself
    and treats them as untrusted data.
    """

    installation_id: str
    repository: str
    pr_number: int
    comment_id: int
    comment_url: str
    commenter_github_id: int
    commenter_login: str
    verb: str
    argument: str
    ambiguous: bool = False


@frozen
class Dropped:
    reason: DropReason


def read_comment_command(payload: Mapping[str, object]) -> CommentCommandRequest | Dropped:
    if payload.get("action") != "created":
        # An edit could turn a reviewed comment into a command after the fact, and a deletion
        # carries nothing to run. Only a new comment is a request.
        return Dropped(reason="not_created")

    issue = _mapping(payload.get("issue"))
    if not _mapping(issue.get("pull_request")):
        return Dropped(reason="not_pull_request")

    comment = _mapping(payload.get("comment"))
    body = comment.get("body")
    parsed = parse_command(body) if isinstance(body, str) else None
    if parsed is None:
        return Dropped(reason="no_command")

    author = _mapping(comment.get("user"))
    login = author.get("login")
    if author.get("type") != "User" or (isinstance(login, str) and login.lower().endswith("[bot]")):
        # Our own replies and other bots' comments can repeat a command. They must never run one.
        return Dropped(reason="bot_author")
    if comment.get("performed_via_github_app"):
        # A GitHub App, coding agents included, posted this with a person's token. The person did
        # not type it, so it is not their request.
        return Dropped(reason="app_authored")
    if str(comment.get("author_association") or "").upper() not in TRUSTED_ASSOCIATIONS:
        return Dropped(reason="untrusted_association")

    installation_id = _positive_int(_mapping(payload.get("installation")).get("id"))
    repository = _mapping(payload.get("repository")).get("full_name")
    pr_number = _positive_int(issue.get("number"))
    comment_id = _positive_int(comment.get("id"))
    comment_url = comment.get("html_url")
    commenter_id = _positive_int(author.get("id"))
    if (
        installation_id is None
        or not isinstance(repository, str)
        or not REPOSITORY_NAME_RE.fullmatch(repository)
        or pr_number is None
        or comment_id is None
        or not isinstance(comment_url, str)
        or commenter_id is None
        or not isinstance(login, str)
        or not login
    ):
        return Dropped(reason="malformed")

    return CommentCommandRequest(
        installation_id=str(installation_id),
        repository=repository,
        pr_number=pr_number,
        comment_id=comment_id,
        comment_url=comment_url,
        commenter_github_id=commenter_id,
        commenter_login=login,
        verb=parsed.verb if isinstance(parsed, ParsedCommand) else "",
        argument=parsed.argument if isinstance(parsed, ParsedCommand) else "",
        ambiguous=isinstance(parsed, AmbiguousCommand),
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
