"""The command contract: what a handler receives and what it answers.

A handler is the only place that knows the product it dispatches into. Everything that decides
whether a command may run at all lives in ``dispatch.py`` and runs before any handler, so a new
command inherits the full set of checks by being declared in ``schema.py``.
"""

from posthog.dataclasses import frozen

from .intake import CommentCommandRequest


@frozen
class PullRequestFacts:
    """What GitHub reported about the pull request when the task read it.

    Read from the API rather than the webhook payload, so the head commit is the one that existed
    after the commenter's permission was confirmed. Free text such as the title and body is not
    kept: nothing here can carry an instruction.
    """

    repository: str
    number: int
    url: str
    state: str
    draft: bool
    head_sha: str
    head_branch: str
    is_fork: bool


@frozen
class CommandContext:
    request: CommentCommandRequest
    pull_request: PullRequestFacts
    user_id: int
    # Projects the commenter may act in for this command, best candidate first. Every id here
    # passed the membership, rollout and resource-access checks for this command.
    team_ids: tuple[int, ...]


@frozen
class CommandOutcome:
    accepted: bool
    # Markdown posted back on the pull request. Handlers build it from fixed text and values
    # PostHog or GitHub produced, never from the comment, so a reply cannot be made to say
    # something the commenter wrote.
    message: str
