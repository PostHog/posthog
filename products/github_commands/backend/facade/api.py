"""Facade for github_commands.

The ONLY module other products and core may import. It stays cheap to import, because the webhook
consumer calls it inside the request for every comment on every pull request.
"""

from __future__ import annotations

from collections.abc import Mapping

import structlog

from ..logic.intake import CommentCommandRequest, Dropped, read_comment_command

logger = structlog.get_logger(__name__)

__all__ = ["accept_issue_comment"]


def accept_issue_comment(payload: Mapping[str, object]) -> None:
    """Queue the command in a verified ``issue_comment`` payload, if it holds one.

    Most comments are not commands and stop here without touching the database or the queue.
    """
    request = read_comment_command(payload)
    if isinstance(request, Dropped):
        if request.reason not in ("not_created", "not_pull_request", "no_command"):
            logger.info("github_command_dropped", reason=request.reason)
        return
    _enqueue(request)


def _enqueue(request: CommentCommandRequest) -> None:
    # Deferred: the task module imports every product facade a command dispatches into, and most
    # comments never get this far.
    from ..tasks.tasks import run_comment_command  # noqa: PLC0415

    run_comment_command.delay(
        installation_id=request.installation_id,
        repository=request.repository,
        pr_number=request.pr_number,
        comment_id=request.comment_id,
        comment_url=request.comment_url,
        commenter_github_id=request.commenter_github_id,
        commenter_login=request.commenter_login,
        verb=request.verb,
        argument=request.argument,
        ambiguous=request.ambiguous,
    )
