"""Reconciles the sandbox's live session identities to the run's current actor.

A sandbox holds two per-user credential surfaces: the ACP session's MCP OAuth
token and the git/gh credentials (token, author, PR authorship) frozen into the
workspace. Each is minted for one user at a time, while the run's actor can
change between messages (multiplayer Slack threads). ``ensure_sandbox_identity``
is the single choke point where, right before a follow-up turn is delivered,
every surface is compared against the identity last pushed to this sandbox and
rebound when the speaker changed.

Freshness differs per surface: the MCP token has no other refresh path, so its
TTL window is enforced here too; GitHub tokens are kept alive between messages
by the credential-refresh loop, so the GitHub gate only reacts to identity
transitions.
"""

import time
from typing import TYPE_CHECKING

import structlog

from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.logic.services.agent_command import REFRESH_TIMEOUT_SECONDS, send_refresh_session
from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.models import TaskRun
from products.tasks.backend.temporal.oauth import create_oauth_access_token_for_run
from products.tasks.backend.temporal.process_task.sandbox_credentials import (
    GitHubSandboxCredential,
    notify_sandbox_credentials_refreshed,
)
from products.tasks.backend.temporal.process_task.utils import (
    SandboxIdentityKind,
    get_last_sandbox_identity,
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
    mark_mcp_session,
    mark_sandbox_identity,
    sandbox_identity_scope,
    should_refresh_mcp_token,
)

if TYPE_CHECKING:
    from posthog.models.user import User

    from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import (
        TaskProcessingContext,
    )

logger = structlog.get_logger(__name__)

REFRESH_RETRY_DELAY_SECONDS = 0.5


def ensure_sandbox_identity(
    task_run: TaskRun,
    actor_user: "User | None",
    *,
    posthog_mcp_scopes: PosthogMcpScopes,
    auth_token: str | None,
    processing_context: "TaskProcessingContext | None" = None,
) -> None:
    """Rebind the sandbox's live session to the run's current actor.

    ``actor_user`` is the caller's already-resolved credential user
    (``get_task_run_credential_user``); None means no valid actor (Slack
    fail-closed), which the MCP mint surfaces as its standard warning.

    Best-effort and never raises: a failed rebind must not block an
    otherwise-valid follow-up, and an unmarked failure is retried on the next
    message. The GitHub surface is only reconciled when the caller supplies
    the run's processing context (older in-flight workflows don't).
    """
    run_id = str(task_run.id)
    scope = sandbox_identity_scope(run_id, task_run.state)
    try:
        _ensure_mcp_identity(task_run, actor_user, scope, posthog_mcp_scopes, auth_token)
    except Exception:
        logger.warning("sandbox_identity_reconcile_failed", kind="mcp", run_id=run_id, exc_info=True)
    if actor_user is not None and processing_context is not None:
        try:
            _ensure_github_identity(task_run, actor_user, scope, processing_context, auth_token)
        except Exception:
            logger.warning("sandbox_identity_reconcile_failed", kind="github", run_id=run_id, exc_info=True)


def _last_bound_identity(task_run: TaskRun, scope: str, kind: SandboxIdentityKind) -> int | str | None:
    """The identity the sandbox's session currently holds for a surface.

    Until a rebind records otherwise, the sandbox holds its boot-time
    credentials, which were minted for the task creator — so an absent mark
    (never written, evicted, or pre-rollout sandbox) defaults to the creator.
    """
    return get_last_sandbox_identity(scope, kind) or task_run.task.created_by_id


def _ensure_mcp_identity(
    task_run: TaskRun,
    actor_user: "User | None",
    scope: str,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
) -> None:
    """Skip only when the session already holds a fresh token for this actor:
    the freshness window is keyed per (sandbox, user), and an actor transition
    bypasses the window entirely. A missing actor (Slack fail-closed) falls
    through to the mint, which surfaces the standard warning."""
    run_id = str(task_run.id)
    if actor_user is not None:
        last_identity = _last_bound_identity(task_run, scope, "mcp")
        identity_changed = actor_user.id != last_identity
        if not identity_changed and not should_refresh_mcp_token(scope, actor_user.id):
            logger.info("refresh_mcp_skipped_within_interval", run_id=run_id, user_id=actor_user.id)
            return
        if identity_changed:
            logger.info(
                "refresh_mcp_identity_transition",
                run_id=run_id,
                previous_user_id=last_identity,
                user_id=actor_user.id,
            )
    _rebind_mcp(task_run, actor_user, scope, scopes, auth_token)


def _rebind_mcp(
    task_run: TaskRun,
    actor_user: "User | None",
    scope: str,
    scopes: PosthogMcpScopes,
    auth_token: str | None,
) -> None:
    """Mint a fresh OAuth token for the actor and push updated MCP configs to
    the sandbox. Retries once on failure, then logs and returns."""
    run_id = str(task_run.id)
    task = task_run.task
    try:
        access_token = create_oauth_access_token_for_run(task, task_run.state, scopes=scopes)
    except Exception as e:
        logger.warning("refresh_mcp_token_mint_failed", run_id=run_id, error=str(e))
        return

    mcp_configs = get_sandbox_ph_mcp_configs(
        token=access_token,
        project_id=task_run.team_id,
        scopes=scopes,
        interaction_origin=(task_run.state or {}).get("interaction_origin"),
        task_id=str(task_run.task_id),
    )
    if actor_user and actor_user.id:
        user_mcp_configs = get_user_mcp_server_configs(
            token=access_token,
            team_id=task_run.team_id,
            user_id=actor_user.id,
            interaction_origin=(task_run.state or {}).get("interaction_origin"),
        )
        if user_mcp_configs:
            mcp_configs = mcp_configs + user_mcp_configs

    if not mcp_configs:
        # Nothing to push means there is no MCP session to rebind — mark the
        # window anyway so we don't re-mint a token on every message.
        if actor_user is not None:
            mark_mcp_session(scope, actor_user.id)
        logger.info("refresh_mcp_skipped_no_configs", run_id=run_id)
        return

    mcp_servers = [config.to_dict() for config in mcp_configs]

    for attempt in (1, 2):
        result = send_refresh_session(
            task_run,
            mcp_servers,
            auth_token=auth_token,
            timeout=REFRESH_TIMEOUT_SECONDS,
        )
        if result.success:
            if actor_user is not None:
                mark_mcp_session(scope, actor_user.id)
            logger.info("refresh_mcp_delivered", run_id=run_id, attempts=attempt)
            return
        if attempt == 1:
            logger.info(
                "refresh_mcp_retrying",
                run_id=run_id,
                error=result.error,
                status_code=result.status_code,
            )
            time.sleep(REFRESH_RETRY_DELAY_SECONDS)
        else:
            logger.warning(
                "refresh_mcp_failed",
                run_id=run_id,
                error=result.error,
                status_code=result.status_code,
            )


def _ensure_github_identity(
    task_run: TaskRun,
    actor_user: "User",
    scope: str,
    processing_context: "TaskProcessingContext",
    auth_token: str | None,
) -> None:
    """Transition-only gate: token TTL between messages is owned by the
    credential-refresh loop, so this fires only when the speaker changed."""
    run_id = str(task_run.id)
    if not processing_context.has_github_credentials:
        return
    sandbox_id = (task_run.state or {}).get("sandbox_id")
    if not sandbox_id:
        # Nowhere to push yet; the boot path binds the identity itself.
        return
    last_identity = _last_bound_identity(task_run, scope, "github")
    if actor_user.id == last_identity:
        return
    logger.info(
        "refresh_github_identity_transition",
        run_id=run_id,
        previous_user_id=last_identity,
        user_id=actor_user.id,
    )
    if _rebind_github(task_run, sandbox_id, processing_context, auth_token):
        mark_sandbox_identity(scope, "github", actor_user.id)


def _rebind_github(
    task_run: TaskRun,
    sandbox_id: str,
    processing_context: "TaskProcessingContext",
    auth_token: str | None,
) -> bool:
    """Re-inject the actor's GitHub credentials (token + git author) into the
    live sandbox. Returns True when the sandbox now reflects the actor (or
    there is nothing to rebind), False when the rebind should be retried on
    the next message."""
    run_id = str(task_run.id)
    live_context = processing_context.with_state(task_run.state)
    try:
        sandbox = Sandbox.get_by_id(sandbox_id)
        outcome = GitHubSandboxCredential().refresh(sandbox, live_context, task_run.task)
    except Exception:
        logger.warning("refresh_github_identity_failed", run_id=run_id, exc_info=True)
        return False

    if not outcome.refreshed:
        # No refreshable GitHub credential in play (e.g. caller-token run) —
        # nothing to diverge on; mark so we don't retry every message.
        return True

    notify = notify_sandbox_credentials_refreshed(task_run, ["github"], auth_token=auth_token)
    if not notify.success:
        # Credentials already landed in the sandbox; the notification only
        # feeds the agent-server's debug log.
        logger.info("refresh_github_notify_failed", run_id=run_id, error=notify.error)
    logger.info("refresh_github_delivered", run_id=run_id)
    return True
