"""Decides whether a comment command runs, then runs it.

Every command passes the same checks, in this order, before its handler runs:

1. A project on this installation is in the rollout. Until one is, nothing below runs and the bot
   says nothing.
2. The comment is new to us. Ingress dedups the delivery, and this claims the comment itself, so
   a redelivery or a second consumer path cannot run one comment twice.
3. The commenter is within their rate limit. This runs before any GitHub call, so a flood of
   comments costs no GitHub quota.
4. GitHub says the commenter's account, matched by its numeric id, can write to the repository.
   The webhook's `author_association` only filtered noise; organization members can lack write
   access to a given repository.
5. The comment holds exactly one command, the command exists, and its arguments match its grammar.
6. The commenter's GitHub account is linked to exactly one active PostHog user, and that user is a
   member of a rolled-out project whose GitHub integration uses this installation.
7. The pull request is open, and the command allows forks if the head is a fork.
8. The user has the access the command declares on the project, in PostHog access control.

People who fail checks 1 to 4 get no answer at all, so the bot gives outsiders nothing to probe and
no way to make it post. Everyone past them gets a reply that says what happened.
"""

from collections.abc import Callable
from typing import Any, Literal

from django.core.cache import cache

import structlog
from prometheus_client import Counter

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.exceptions_capture import capture_exception
from posthog.models.integration import Integration
from posthog.models.scoping.manager import resolve_effective_team_id
from posthog.models.team import Team
from posthog.models.user import User
from posthog.permissions import UserAccessControl, posthog_feature_flag_enabled
from posthog.token_bucket import BucketDecision, Budget, consume

from .commands import CommandContext
from .github import CommandGitHub, GitHubCallFailed, InstallationGitHub, UnsupportedPullRequest
from .identity import Commenter, resolve_commenter
from .intake import CommentCommandRequest
from .parsing import HELP_VERB
from .registry import COMMANDS, CommandSpec, Invocation, help_text
from .schema import ArgumentError, ResourceAccess, resolve_verb, usage

logger = structlog.get_logger(__name__)

ROLLOUT_FLAG = "github-commands"
_WRITE_PERMISSIONS = frozenset({"admin", "maintain", "write"})
_CLAIM_TTL_SECONDS = 7 * 24 * 60 * 60
# A person typing commands rarely sends more than a few in a row. The cap stops a script or a
# runaway agent with a member's account from fanning out runs that cost money.
_COMMENTER_BUDGET = Budget(burst=5, per_hour=30)

DispatchOutcome = Literal[
    "duplicate",
    "claim_unavailable",
    "not_rolled_out",
    "no_installation",
    "no_write_access",
    "permission_lookup_failed",
    "rate_limited",
    "ambiguous",
    "help",
    "unknown_command",
    "invalid_arguments",
    "unlinked",
    "no_project",
    "pull_request_unavailable",
    "pull_request_unsupported",
    "pull_request_closed",
    "fork_refused",
    "access_denied",
    "accepted",
    "refused",
    "failed",
]

GITHUB_COMMANDS_TOTAL = Counter(
    "posthog_github_commands_total",
    "Pull request comment commands, by command and what dispatch did with them",
    labelnames=["verb", "outcome"],
)


def dispatch_comment_command(request: CommentCommandRequest, *, github: CommandGitHub | None = None) -> DispatchOutcome:
    verb = resolve_verb(request.verb)
    spec = COMMANDS.get(verb) if verb is not None else None
    outcome = _dispatch(request, spec, github)
    # Unknown verbs share one label value, so a comment cannot mint a metric series. Aliases count
    # under their canonical verb.
    verb_label = spec.declaration.verb if spec else (HELP_VERB if request.verb == HELP_VERB else "unknown")
    GITHUB_COMMANDS_TOTAL.labels(verb=verb_label, outcome=outcome).inc()
    logger.info(
        "github_command_dispatched",
        verb=verb_label,
        outcome=outcome,
        repository=request.repository,
        pr_number=request.pr_number,
        comment_id=request.comment_id,
    )
    return outcome


@frozen
class _Admitted:
    github: CommandGitHub
    rolled_out_team_ids: frozenset[int]


@frozen
class _Answer:
    """Dispatch stops here and tells the commenter why."""

    outcome: DispatchOutcome
    message: str


def _dispatch(
    request: CommentCommandRequest, spec: CommandSpec[Any] | None, github: CommandGitHub | None
) -> DispatchOutcome:
    admitted = _admit(request, github)
    if not isinstance(admitted, _Admitted):
        return admitted
    github = admitted.github
    github.react(request.repository, request.comment_id, "eyes")

    def reply(message: str) -> None:
        github.reply(request.repository, request.pr_number, _reply_body(request, message))

    command = _runnable_command(request, spec)
    if isinstance(command, _Answer):
        reply(command.message)
        return command.outcome

    context = _command_context(request, command.spec, github, admitted.rolled_out_team_ids)
    if isinstance(context, _Answer):
        reply(context.message)
        return context.outcome
    return _run(command, context, github, reply)


def _admit(request: CommentCommandRequest, github: CommandGitHub | None) -> _Admitted | DispatchOutcome:
    """The checks that stay silent: nobody who fails one hears from the bot."""
    # Before any GitHub call: the App is installed on repositories of organizations that never
    # turned commands on, and the bot must stay silent there.
    rolled_out_team_ids = _rolled_out_team_ids(request.installation_id)
    if not rolled_out_team_ids:
        return "not_rolled_out"
    claim_refusal = _claim_comment(request.comment_id)
    if claim_refusal is not None:
        return claim_refusal
    if not _within_rate_limit(request.commenter_github_id):
        return "rate_limited"
    if github is None:
        github = InstallationGitHub.for_installation(request.installation_id)
        if github is None:
            return "no_installation"
    try:
        permission = github.collaborator_permission(
            request.repository, request.commenter_login, request.commenter_github_id
        )
    except GitHubCallFailed:
        logger.warning("github_command_permission_lookup_failed", repository=request.repository, exc_info=True)
        # Nothing ran, so a redelivery may try again.
        _release_comment(request.comment_id)
        return "permission_lookup_failed"
    if permission not in _WRITE_PERMISSIONS:
        return "no_write_access"
    return _Admitted(github=github, rolled_out_team_ids=rolled_out_team_ids)


def _runnable_command(request: CommentCommandRequest, spec: CommandSpec[Any] | None) -> Invocation[Any] | _Answer:
    """The command to run, or the answer to a request that needs no PostHog account: help, and
    comments with no runnable command."""
    if request.ambiguous:
        return _Answer(outcome="ambiguous", message="Put one command in a comment, so it is clear which one to run.")
    if request.verb == HELP_VERB:
        return _Answer(outcome="help", message=help_text())
    if spec is None:
        return _Answer(outcome="unknown_command", message="I don't know that command.\n\n" + help_text())
    invocation = spec.parse(request.argument)
    if isinstance(invocation, ArgumentError):
        return _Answer(outcome="invalid_arguments", message=f"{invocation.reason} Use `{usage(spec.declaration)}`.")
    return invocation


def _command_context(
    request: CommentCommandRequest,
    spec: CommandSpec[Any],
    github: CommandGitHub,
    rolled_out_team_ids: frozenset[int],
) -> CommandContext | _Answer:
    declaration = spec.declaration
    commenter = resolve_commenter(github_user_id=request.commenter_github_id, installation_id=request.installation_id)
    if not isinstance(commenter, Commenter):
        return _Answer(outcome="unlinked", message=_UNRESOLVED_MESSAGES[commenter.reason])
    team_ids = tuple(team_id for team_id in commenter.team_ids if team_id in rolled_out_team_ids)
    if not team_ids:
        return _Answer(
            outcome="no_project",
            message="You aren't a member of a PostHog project that uses pull request commands on this repository.",
        )

    try:
        pull_request = github.pull_request(request.repository, request.pr_number)
    except GitHubCallFailed:
        pull_request = None
    except UnsupportedPullRequest:
        return _Answer(
            outcome="pull_request_unsupported",
            message="I only run commands on pull requests whose branch name uses letters, digits, `.`, `_`, `/` and `-`.",
        )
    if pull_request is None:
        return _Answer(
            outcome="pull_request_unavailable",
            message="I couldn't read this pull request from GitHub. Try again in a few minutes.",
        )
    if pull_request.state != "open":
        return _Answer(
            outcome="pull_request_closed", message="This pull request isn't open, so I won't run commands on it."
        )
    if pull_request.is_fork and not declaration.allows_forks:
        return _Answer(outcome="fork_refused", message=f"`{declaration.verb}` doesn't run on pull requests from forks.")

    access = declaration.access
    if access is not None:
        team_ids = _teams_with_access(User.objects.get(id=commenter.user_id), team_ids, access)
        if not team_ids:
            return _Answer(
                outcome="access_denied",
                message=f"You need {access.level} access to {access.resource} in PostHog to use `{declaration.verb}`.",
            )
    return CommandContext(request=request, pull_request=pull_request, user_id=commenter.user_id, team_ids=team_ids)


_UNRESOLVED_MESSAGES = {
    "unlinked": "Your GitHub account is not linked to a PostHog account, so I can't tell who to run this as. "
    "Connect GitHub in your PostHog personal settings, then comment again.",
    "ambiguous": "Your GitHub account is linked to more than one PostHog account, so I can't tell which to run this "
    "as. Disconnect GitHub from the accounts you don't use, then comment again.",
}


def _run(
    command: Invocation[Any], context: CommandContext, github: CommandGitHub, reply: Callable[[str], None]
) -> DispatchOutcome:
    verb = command.spec.declaration.verb
    try:
        outcome = command.run(context)
    except GitHubRateLimitError:
        reply("GitHub is limiting how fast PostHog can work on this repository. Try again in a few minutes.")
        return "failed"
    except Exception as error:
        capture_exception(error)
        logger.exception("github_command_failed", verb=verb, comment_id=context.request.comment_id)
        reply(f"Something went wrong while running `{verb}`. Try again in a few minutes.")
        return "failed"
    reply(outcome.message)
    if outcome.accepted:
        github.react(context.request.repository, context.request.comment_id, "rocket")
        return "accepted"
    return "refused"


def _reply_body(request: CommentCommandRequest, message: str) -> str:
    # The marker lets a reader find the comment a reply answers. The login is GitHub's, not text
    # from the comment, so the mention pings only the person who asked.
    return f"<!-- posthog-github-command:{request.comment_id} -->\n@{request.commenter_login} {message}"


def _claim_key(comment_id: int) -> str:
    return f"github_commands:comment:{comment_id}"


def _claim_comment(comment_id: int) -> DispatchOutcome | None:
    """None when this call claimed the comment, else the outcome that stops dispatch."""
    try:
        claimed = cache.add(_claim_key(comment_id), 1, timeout=_CLAIM_TTL_SECONDS)
    except Exception:
        # Fail closed: the cache shares Redis with the Celery broker, so an outage that drops this
        # command drops it anyway, while failing open lets a redelivery start a second paid run.
        logger.warning("github_command_claim_failed", comment_id=comment_id, exc_info=True)
        return "claim_unavailable"
    return None if claimed else "duplicate"


def _release_comment(comment_id: int) -> None:
    try:
        cache.delete(_claim_key(comment_id))
    except Exception:
        logger.warning("github_command_release_failed", comment_id=comment_id, exc_info=True)


def _within_rate_limit(github_user_id: int) -> bool:
    decision = consume(f"github_commands:commenter:{github_user_id}", _COMMENTER_BUDGET)
    # Fail open when Redis can't answer, like the other per-caller buckets.
    return not isinstance(decision, BucketDecision) or decision.allowed


def _rolled_out_team_ids(installation_id: str) -> frozenset[int]:
    """Projects on this installation whose organization is in the rollout."""
    team_ids = set(
        Integration.objects.filter(kind="github", integration_id=installation_id).values_list("team_id", flat=True)
    )
    teams = Team.objects.filter(id__in=team_ids).only("id", "organization_id")
    return frozenset(
        team.id
        for team in teams
        if posthog_feature_flag_enabled(
            ROLLOUT_FLAG,
            # The rollout targets organizations, so the person behind the comment does not matter yet.
            f"github-commands-installation-{installation_id}",
            organization_id=team.organization_id,
            team_id=team.id,
        )
    )


def _teams_with_access(user: User, team_ids: tuple[int, ...], access: ResourceAccess) -> tuple[int, ...]:
    # Products keep their rows, and their access rules, on the parent project.
    effective_team_ids = {team_id: resolve_effective_team_id(team_id) for team_id in team_ids}
    teams = Team.objects.in_bulk(set(effective_team_ids.values()))
    has_access: dict[int, bool] = {}
    for effective_team_id, team in teams.items():
        access_control = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
        has_access[effective_team_id] = access_control.check_access_level_for_resource(access.resource, access.level)
    return tuple(team_id for team_id in team_ids if has_access.get(effective_team_ids[team_id], False))
