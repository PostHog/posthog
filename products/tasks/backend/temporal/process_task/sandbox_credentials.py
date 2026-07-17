"""Refresh long-lived credentials inside a running task sandbox by re-resolving and re-applying tokens in place."""

import shlex
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from django.db import transaction

import redis

from posthog.models.integration import Integration
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration, UserIntegration
from posthog.redis import get_client

from products.tasks.backend.exceptions import CredentialUnavailableError
from products.tasks.backend.logic.services.agentsh import GITHUB_ENV_FILE, OAUTH_ENV_FILE
from products.tasks.backend.logic.services.run_actor import loop_owner_eligible_for_credentials
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.utils import (
    PrAuthorshipMode,
    get_github_token,
    get_pr_authorship_mode,
    get_readonly_github_token,
    get_sandbox_github_identity_user,
    get_sandbox_github_token,
    get_task_run_credential_user,
    is_caller_token_run,
    is_slack_interaction_state,
    resolve_user_github_integration_for_task,
    sandbox_identity_scope,
)

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.sandbox import SandboxBase

    from .activities.get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

GITHUB_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")
OAUTH_ENV_KEY = "POSTHOG_PERSONAL_API_KEY"

# Refresh at half the token's server-side half-life so the in-sandbox copy never lapses mid-run.
#   ghs_ = installation token (~1h) → 20 min; ghu_ = user-to-server token (~8h) → 2 h
_GITHUB_REFRESH_INTERVAL_BY_PREFIX: dict[str, float] = {
    "ghs_": 20 * 60,
    "ghu_": 2 * 60 * 60,
}
DEFAULT_REFRESH_INTERVAL_SECONDS: float = 20 * 60


def github_refresh_interval_seconds(token: str) -> float:
    for prefix, interval in _GITHUB_REFRESH_INTERVAL_BY_PREFIX.items():
        if token.startswith(prefix):
            return interval
    return DEFAULT_REFRESH_INTERVAL_SECONDS


def set_git_remote_token(sandbox: "SandboxBase", repository: str, github_token: str | None) -> bool:
    """Rewrite ``origin`` with the current credential state; git re-reads it on every operation."""
    org, repo = repository.lower().split("/")
    repo_path = f"/tmp/workspace/repos/{org}/{repo}"
    if github_token:
        remote_url = f"https://x-access-token:{github_token}@github.com/{repository}.git"
    else:
        remote_url = f"https://github.com/{repository}.git"
    update_remote = (
        f"if [ -d {shlex.quote(repo_path + '/.git')} ]; then "
        f"cd {shlex.quote(repo_path)} && "
        f"git remote set-url origin {shlex.quote(remote_url)}; "
        f"fi"
    )
    result = sandbox.execute(update_remote, timeout_seconds=30)
    if result.exit_code != 0:
        logger.warning(
            "Failed to refresh git remote URL",
            extra={"sandbox_id": sandbox.id, "repository": repository, "stderr": result.stderr},
        )
        return False
    return True


def _write_sandbox_credential_file(sandbox: "SandboxBase", path: str, payload: bytes) -> bool:
    """Atomically replace one credential domain without a cross-key read-modify-write."""
    write = sandbox.write_file(path, payload)
    if write.exit_code != 0:
        logger.warning(
            "Failed to refresh sandbox credential file",
            extra={"sandbox_id": sandbox.id, "credential_file": path, "stderr": write.stderr},
        )
        return False

    chmod = sandbox.execute(f"chmod 600 {shlex.quote(path)}", timeout_seconds=30)
    if chmod.exit_code != 0:
        logger.warning(
            "Failed to restrict sandbox credential file permissions",
            extra={"sandbox_id": sandbox.id, "credential_file": path, "stderr": chmod.stderr},
        )
        return False
    return True


def replace_sandbox_credentials(
    sandbox: "SandboxBase", github_token: str | None, oauth_access_token: str | None
) -> bool:
    """Replace every managed credential, including empty values that revoke stale snapshot state."""
    github_payload = b"".join(f"{key}={github_token}\x00".encode() for key in GITHUB_ENV_KEYS) if github_token else b""
    oauth_payload = f"{OAUTH_ENV_KEY}={oauth_access_token}\x00".encode() if oauth_access_token else b""

    github_updated = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, github_payload)
    oauth_updated = _write_sandbox_credential_file(sandbox, OAUTH_ENV_FILE, oauth_payload)
    return github_updated and oauth_updated


def apply_github_credentials_to_sandbox(sandbox: "SandboxBase", repository: str | None, github_token: str) -> bool:
    """Re-inject a GitHub token into both places a running sandbox reads it from.

    Returns ``True`` only when every applicable write succeeded. A caller enforcing per-actor
    identity must treat a partial write as an unconfirmed rebind: leaving one location on the
    previous actor's token would let a follow-up actor act as them.
    """
    remote_applied = set_git_remote_token(sandbox, repository, github_token) if repository else True
    github_payload = b"".join(f"{key}={github_token}\x00".encode() for key in GITHUB_ENV_KEYS)
    env_applied = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, github_payload)
    return remote_applied and env_applied


def clear_github_credentials_from_sandbox(sandbox: "SandboxBase", repository: str | None) -> bool:
    """Log the sandbox out of GitHub: strip the token from the git remote and blank the GitHub
    credential file, so a follow-up actor who lacks access can't reuse the previous actor's token.
    Returns ``True`` only when both were cleared.
    """
    remote_cleared = set_git_remote_token(sandbox, repository, None) if repository else True
    env_cleared = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, b"")
    return remote_cleared and env_cleared


def _loop_owner_credentials_revoked(task: Task, state: dict | None) -> bool:
    """Post-resolution eligibility gate for every path that injects a GitHub token into a LOOP
    sandbox, mirroring `get_sandbox_github_token`: a loop run alive during or after its owner's
    deactivation or team-access revocation must not receive a fresh token, whichever refresh path
    resolved it (user-integration refresh, installation fallback, read-only re-mint, or sibling
    propagation). Non-loop runs are unaffected."""
    if (state or {}).get("loop_id") is None:
        return False
    with transaction.atomic():
        eligible = loop_owner_eligible_for_credentials(task.created_by_id, task.team)
    if not eligible:
        logger.warning(
            "loop_github_refresh_owner_ineligible",
            extra={"task_id": str(task.id)},
        )
    return not eligible


USER_TOKEN_REFRESH_INTERVAL_SECONDS: float = _GITHUB_REFRESH_INTERVAL_BY_PREFIX["ghu_"]
# TTL covers a slow mint + propagation; wait stays under the refresh activity's 2 min timeout.
_ROTATION_LOCK_TTL_SECONDS = 120
_ROTATION_LOCK_WAIT_SECONDS = 90


def _rotation_lock_key(user_integration_id: int) -> str:
    return f"tasks:gh_user_token_rotate:{user_integration_id}"


def _live_sandboxes_for_user_integration(user_integration_id: int) -> list[tuple[str, str, str | None]]:
    rows: list[tuple[str, str, str | None]] = []
    runs = TaskRun.objects.filter(
        status=TaskRun.Status.IN_PROGRESS,
        task__github_user_integration_id=user_integration_id,
    ).select_related("task", "task__team")
    for run in runs:
        sandbox_id = (run.state or {}).get("sandbox_id")
        if not sandbox_id:
            continue
        # Only user-authored runs use this integration's rotating token. Bot-authored runs use an
        # installation token, and caller-supplied-token runs are pinned to their own credential —
        # propagating over either would swap its identity.
        if get_pr_authorship_mode(run.task, run.state) != PrAuthorshipMode.USER:
            continue
        if is_caller_token_run(str(run.id), run.state):
            continue
        if _loop_owner_credentials_revoked(run.task, run.state):
            continue
        # A per-message actor transition may have rebound (or logged out) this sandbox's GitHub
        # identity to someone other than the run owner. This loop carries the owner's token, so
        # re-applying it would undo that transition and resurrect the owner's identity for the
        # current actor. Skip when the sandbox is bound to a different actor.
        bound_actor = get_sandbox_github_identity_user(sandbox_identity_scope(str(run.id), run.state))
        if bound_actor is not None and bound_actor != run.task.created_by_id:
            continue
        rows.append((str(run.id), sandbox_id, run.task.repository))
    return rows


def _propagate_user_token(user_integration_id: int, token: str) -> int:
    from products.tasks.backend.logic.services.sandbox import Sandbox  # noqa: PLC0415

    applied = 0
    for run_id, sandbox_id, repository in _live_sandboxes_for_user_integration(user_integration_id):
        try:
            sandbox = Sandbox.get_by_id(sandbox_id)
            if sandbox.is_running():
                apply_github_credentials_to_sandbox(sandbox, repository, token)
                applied += 1
        except Exception:
            logger.warning(
                "Failed to propagate refreshed GitHub user token to sibling sandbox",
                extra={"integration_id": user_integration_id, "run_id": run_id, "sandbox_id": sandbox_id},
                exc_info=True,
            )
    return applied


def resolve_coordinated_user_token(integration: UserGitHubIntegration) -> str | None:
    """Usable user-to-server token, with the rotating mint serialized per integration.

    Refreshing a user token revokes the previous one, so concurrent callers sharing an
    integration would revoke each other's in-flight token. Serialize the mint under a
    per-integration lock and propagate the fresh token to live sandboxes.
    """
    if not integration.user_access_token_expired():
        return integration.get_usable_user_access_token()

    integration_id = integration.integration.id
    lock = get_client().lock(
        _rotation_lock_key(integration_id),
        timeout=_ROTATION_LOCK_TTL_SECONDS,
        blocking_timeout=_ROTATION_LOCK_WAIT_SECONDS,
    )
    if not lock.acquire():
        # Waited out the budget — read the current token without minting; the holder's propagation self-heals.
        integration.integration.refresh_from_db()
        return UserGitHubIntegration(integration.integration).user_access_token

    try:
        integration.integration.refresh_from_db()
        current = UserGitHubIntegration(integration.integration)
        was_expired = current.user_access_token_expired()
        # Mints only if still expired; a prior holder's fresh token is returned without rotating.
        token = current.get_usable_user_access_token()
        if was_expired and token:
            propagated = _propagate_user_token(integration_id, token)
            logger.info(
                "Rotated and propagated GitHub user token",
                extra={"integration_id": integration_id, "sibling_sandboxes_updated": propagated},
            )
        return token
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            logger.warning(
                "GitHub user-token rotation lock already expired/released",
                extra={"integration_id": integration_id},
            )


@dataclass
class CredentialRefreshOutcome:
    kind: str
    refreshed: bool
    next_refresh_seconds: float


class SandboxCredential(Protocol):
    """A long-lived secret that can be re-resolved and re-applied to a sandbox.

    Implementations own their own token resolution, sandbox application, and
    refresh cadence, so the refresh activity is agnostic to credential type.
    """

    kind: str

    def refresh(self, sandbox: "SandboxBase", ctx: "TaskProcessingContext", task: Task) -> CredentialRefreshOutcome: ...


@dataclass
class GitHubSandboxCredential:
    """Refreshes the GitHub token (user *or* installation, per authorship)."""

    kind: str = "github"

    def refresh(self, sandbox: "SandboxBase", ctx: "TaskProcessingContext", task: Task) -> CredentialRefreshOutcome:
        # A repo-less read-only run must stay read-only for its whole lifetime: without this
        # guard the periodic refresh would resolve the full credential path (the team integration
        # is attached to every task) and silently swap the downscoped token for the write-capable
        # one mid-run. Re-mint the same read-only grant instead; best-effort like the original.
        if ctx.github_read_access and ctx.repository is None:
            token = get_readonly_github_token(ctx.team_id)
            if token and _loop_owner_credentials_revoked(task, ctx.state):
                token = None
            if token:
                apply_github_credentials_to_sandbox(sandbox, None, token)
            return CredentialRefreshOutcome(
                self.kind,
                refreshed=bool(token),
                next_refresh_seconds=github_refresh_interval_seconds(token)
                if token
                else DEFAULT_REFRESH_INTERVAL_SECONDS,
            )
        if not ctx.has_github_credentials:
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )

        # A per-message actor transition may have rebound (or logged out) this sandbox's GitHub
        # identity to someone other than the run owner. This scheduled refresh resolves the actor
        # from the startup context (ctx.state), so it carries the owner's token; re-applying it
        # would resurrect the owner's identity over the current actor's session. Skip and leave the
        # transition's binding intact — the per-message gate keeps the current actor's token fresh.
        bound_actor = get_sandbox_github_identity_user(sandbox_identity_scope(ctx.run_id, ctx.state))
        if bound_actor is not None and bound_actor != task.created_by_id:
            logger.info(
                "github_refresh_skipped_actor_transition",
                extra={"run_id": ctx.run_id, "bound_actor": bound_actor, "owner": task.created_by_id},
            )
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )

        actor_user = get_task_run_credential_user(task, ctx.state)
        if is_slack_interaction_state(ctx.state) and actor_user is None:
            raise ReauthorizationRequired("Slack run requires an acting user before refreshing GitHub credentials.")

        integration = None
        if get_pr_authorship_mode(task, ctx.state) == PrAuthorshipMode.USER and not is_caller_token_run(
            ctx.run_id, ctx.state
        ):
            integration = resolve_user_github_integration_for_task(
                task,
                actor_user=actor_user,
                repository=ctx.repository,
                allow_refresh=True,
            )

        if integration is not None:
            return self._refresh_shared_user_integration(sandbox, ctx, task, integration)

        github_integration_id = task.github_integration_id
        github_user_integration_id = (
            str(task.github_user_integration_id) if task.github_user_integration_id else ctx.github_user_integration_id
        )
        if (
            github_integration_id is None
            and github_user_integration_id is None
            and not is_caller_token_run(ctx.run_id, ctx.state)
        ):
            raise CredentialUnavailableError(
                "GitHub integration for this run was disconnected mid-run",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
            )

        try:
            token = get_sandbox_github_token(
                github_integration_id,
                run_id=ctx.run_id,
                state=ctx.state,
                task=task,
                actor_user=actor_user,
                github_user_integration_id=github_user_integration_id,
                repository=ctx.repository,
            )
        except (Integration.DoesNotExist, UserIntegration.DoesNotExist) as e:
            raise CredentialUnavailableError(
                "GitHub integration for this run no longer exists",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=e,
            )
        except ReauthorizationRequired as e:
            raise CredentialUnavailableError(
                "GitHub user integration for this run requires reauthorization",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=e,
            )
        if not token:
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )

        apply_github_credentials_to_sandbox(sandbox, ctx.repository, token)
        return CredentialRefreshOutcome(
            self.kind, refreshed=True, next_refresh_seconds=github_refresh_interval_seconds(token)
        )

    def _refresh_shared_user_integration(
        self, sandbox: "SandboxBase", ctx: "TaskProcessingContext", task: Task, integration: UserGitHubIntegration
    ) -> CredentialRefreshOutcome:
        try:
            token = resolve_coordinated_user_token(integration)
        except (ReauthorizationRequired, UserIntegration.DoesNotExist) as e:
            fallback = self._installation_token_fallback(ctx, task, cause=e)
            if fallback and _loop_owner_credentials_revoked(task, ctx.state):
                fallback = None
            if not fallback:
                return CredentialRefreshOutcome(
                    self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
                )
            apply_github_credentials_to_sandbox(sandbox, ctx.repository, fallback)
            return CredentialRefreshOutcome(
                self.kind, refreshed=True, next_refresh_seconds=github_refresh_interval_seconds(fallback)
            )
        if token and _loop_owner_credentials_revoked(task, ctx.state):
            token = None
        if token:
            apply_github_credentials_to_sandbox(sandbox, ctx.repository, token)
        return CredentialRefreshOutcome(
            self.kind, refreshed=bool(token), next_refresh_seconds=USER_TOKEN_REFRESH_INTERVAL_SECONDS
        )

    def _installation_token_fallback(self, ctx: "TaskProcessingContext", task: Task, cause: Exception) -> str | None:
        if task.github_integration_id is None:
            raise CredentialUnavailableError(
                "GitHub user integration requires reauthorization and no team installation is available",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=cause,
            )
        try:
            return get_github_token(task.github_integration_id)
        except Integration.DoesNotExist as e:
            raise CredentialUnavailableError(
                "GitHub integration for this run no longer exists",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=e,
            )


def build_sandbox_credentials(ctx: "TaskProcessingContext") -> list[SandboxCredential]:
    credentials: list[SandboxCredential] = []
    if ctx.has_github_credentials:
        credentials.append(GitHubSandboxCredential())
    return credentials
