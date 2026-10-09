"""Celery tasks for github_commands."""

from celery import shared_task

from ..logic.dispatch import dispatch_comment_command
from ..logic.intake import CommentCommandRequest


# No retries: a command that fails tells the commenter so in a reply, and a silent second attempt
# could start a run they already gave up on.
@shared_task(ignore_result=True, max_retries=0)
def run_comment_command(
    *,
    installation_id: str,
    repository: str,
    pr_number: int,
    comment_id: int,
    comment_url: str,
    commenter_github_id: int,
    commenter_login: str,
    verb: str,
    argument: str,
    ambiguous: bool,
) -> None:
    dispatch_comment_command(
        CommentCommandRequest(
            installation_id=installation_id,
            repository=repository,
            pr_number=pr_number,
            comment_id=comment_id,
            comment_url=comment_url,
            commenter_github_id=commenter_github_id,
            commenter_login=commenter_login,
            verb=verb,
            argument=argument,
            ambiguous=ambiguous,
        )
    )
