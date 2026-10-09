"""The command contract: what a handler receives, what it answers, and how a command is declared.

A handler is the only place that knows the product it dispatches into. Everything that decides
whether a command may run at all lives in ``dispatch.py`` and runs before any handler, so a new
command inherits the full set of checks by being declared here.
"""

from collections.abc import Callable
from typing import Literal

from posthog.dataclasses import frozen
from posthog.scopes import APIScopeObject

from .intake import CommentCommandRequest

AccessLevel = Literal["viewer", "editor", "manager"]


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


@frozen
class ResourceAccess:
    """A PostHog access-control resource the commenter needs on a project for the command."""

    resource: APIScopeObject
    level: AccessLevel


@frozen
class CommandSpec:
    verb: str
    summary: str
    usage: str
    handler: Callable[[CommandContext], CommandOutcome]
    access: ResourceAccess | None = None
    # A fork's head is code nobody with write access has vetted. Commands that run or approve it
    # must refuse forks; only a command that reads nothing from the head may allow them.
    allows_forks: bool = False
    accepts_argument: bool = False

    def __post_init__(self) -> None:
        if not self.verb.isascii() or not self.verb.islower() or " " in self.verb:
            raise ValueError(f"Command verb must be one lowercase word, got {self.verb!r}")
