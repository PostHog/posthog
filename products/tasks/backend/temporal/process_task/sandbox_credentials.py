"""Refresh long-lived credentials inside a running task sandbox by re-resolving and re-applying tokens in place."""

import shlex
import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import redis

from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration
from posthog.redis import get_client

from products.tasks.backend.logic.services.agentsh import ENV_FILE
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.process_task.utils import (
    PrAuthorshipMode,
    get_pr_authorship_mode,
    get_sandbox_github_token,
    get_task_run_credential_user,
    is_caller_token_run,
    is_slack_interaction_state,
    resolve_user_github_integration_for_task,
)

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.sandbox import SandboxBase

    from .activities.get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

GITHUB_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")

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


def set_git_remote_token(sandbox: "SandboxBase", repository: str, github_token: str) -> bool:
    """Rewrite ``origin``'s remote URL with a fresh ``x-access-token``; git re-reads it on every op. No-ops pre-clone."""
    org, repo = repository.lower().split("/")
    repo_path = f"/tmp/workspace/repos/{org}/{repo}"
    update_remote = (
        f"if [ -d {shlex.quote(repo_path + '/.git')} ]; then "
        f"cd {shlex.quote(repo_path)} && "
        f"git remote set-url origin "
        f"https://x-access-token:{shlex.quote(github_token)}@github.com/{shlex.quote(repository)}.git; "
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


def update_sandbox_env_file(sandbox: "SandboxBase", updates: dict[str, str]) -> bool:
    """Replace specific keys in the NUL-delimited agentsh env file, preserving all other entries.

    Read-modify-write via base64 to survive NUL bytes. The exec wrapper re-sources the
    file per command, so updates reach the agent's later ``gh``/``git`` calls without a reboot.
    """
    if not updates:
        return True

    read = sandbox.execute(f"base64 -w0 {shlex.quote(ENV_FILE)} 2>/dev/null || true", timeout_seconds=30)
    existing: bytes = b""
    if read.exit_code == 0 and read.stdout.strip():
        try:
            existing = base64.b64decode(read.stdout.strip())
        except Exception:
            logger.warning("Could not decode existing sandbox env file; rewriting only the updated keys")
            existing = b""

    ordered_keys: list[str] = []
    values: dict[str, bytes] = {}
    for entry in existing.split(b"\x00"):
        if not entry:
            continue
        key_bytes, _, value_bytes = entry.partition(b"=")
        key = key_bytes.decode("utf-8", "replace")
        if key not in values:
            ordered_keys.append(key)
        values[key] = value_bytes

    for key, value in updates.items():
        if key not in values:
            ordered_keys.append(key)
        values[key] = value.encode("utf-8")

    payload = b"".join(f"{key}=".encode() + values[key] + b"\x00" for key in ordered_keys)
    write = sandbox.write_file(ENV_FILE, payload)
    if write.exit_code != 0:
        logger.warning(
            "Failed to refresh agentsh env file",
            extra={"sandbox_id": sandbox.id, "env_file": ENV_FILE, "stderr": write.stderr},
        )
        return False
    return True


def apply_github_credentials_to_sandbox(sandbox: "SandboxBase", repository: str | None, github_token: str) -> None:
    """Re-inject a GitHub token into both places a running sandbox reads it from."""
    if repository:
        set_git_remote_token(sandbox, repository, github_token)
    update_sandbox_env_file(sandbox, dict.fromkeys(GITHUB_ENV_KEYS, github_token))


USER_TOKEN_REFRESH_INTERVAL_SECONDS: float = _GITHUB_REFRESH_INTERVAL_BY_PREFIX["ghu_"]
# TTL covers a slow mint + propagation; wait stays under the refresh activity's 2 min timeout.
_ROTATION_LOCK_TTL_SECONDS = 120
_ROTATION_LOCK_WAIT_SECONDS = 90


def _rotation_lock_key(user_integration_id: int) -> str:
    return f"tasks:gh_user_token_rotate:{user_integration_id}"


def _live_sandboxes_for_user_integration(user_integration_id: int) -> list[tuple[str, str, str | None]]:
    rows: list[tuple[str, str, str | None]] = []
    runs = (
        TaskRun.objects.filter(
            status=TaskRun.Status.IN_PROGRESS,
            task__github_user_integration_id=user_integration_id,
        )
        .select_related("task")
        .only("id", "state", "task__repository", "task__github_user_integration_id", "task__origin_product")
    )
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
        if not ctx.has_github_credentials:
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
            return self._refresh_shared_user_integration(sandbox, ctx, integration)

        token = get_sandbox_github_token(
            ctx.github_integration_id,
            run_id=ctx.run_id,
            state=ctx.state,
            task=task,
            actor_user=actor_user,
            github_user_integration_id=ctx.github_user_integration_id,
            repository=ctx.repository,
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
        self, sandbox: "SandboxBase", ctx: "TaskProcessingContext", integration: UserGitHubIntegration
    ) -> CredentialRefreshOutcome:
        token = resolve_coordinated_user_token(integration)
        if token:
            apply_github_credentials_to_sandbox(sandbox, ctx.repository, token)
        return CredentialRefreshOutcome(
            self.kind, refreshed=bool(token), next_refresh_seconds=USER_TOKEN_REFRESH_INTERVAL_SECONDS
        )


def build_sandbox_credentials(ctx: "TaskProcessingContext") -> list[SandboxCredential]:
    credentials: list[SandboxCredential] = []
    if ctx.has_github_credentials:
        credentials.append(GitHubSandboxCredential())
    return credentials
