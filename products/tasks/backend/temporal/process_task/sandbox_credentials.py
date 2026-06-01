"""
Refresh long-lived credentials inside a running task sandbox.
This module re-resolves a fresh token and re-applies it in place.
"""

import shlex
import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from products.tasks.backend.models import Task
from products.tasks.backend.services.agentsh import ENV_FILE
from products.tasks.backend.temporal.process_task.utils import get_sandbox_github_token

if TYPE_CHECKING:
    from products.tasks.backend.services.sandbox import SandboxBase

    from .activities.get_task_processing_context import TaskProcessingContext

logger = logging.getLogger(__name__)

GITHUB_ENV_KEYS = ("GITHUB_TOKEN", "GH_TOKEN")

# GitHub App tokens are refreshed server-side at their half-life, so a freshly
# resolved token has at least ~half its TTL remaining. Refresh at half of that
# floor again to guarantee the in-sandbox copy never lapses during an active run.
#   ghs_ = installation access token, ~1h TTL  → refresh every 20 min
#   ghu_ = user-to-server token,      ~8h TTL  → refresh every 2 h
_GITHUB_REFRESH_INTERVAL_BY_PREFIX: dict[str, float] = {
    "ghs_": 20 * 60,
    "ghu_": 2 * 60 * 60,
}
# Used before the first token is resolved, and for any unrecognized prefix —
# short enough to stay under the 1h installation-token floor.
DEFAULT_REFRESH_INTERVAL_SECONDS: float = 20 * 60


def github_refresh_interval_seconds(token: str) -> float:
    for prefix, interval in _GITHUB_REFRESH_INTERVAL_BY_PREFIX.items():
        if token.startswith(prefix):
            return interval
    return DEFAULT_REFRESH_INTERVAL_SECONDS


def set_git_remote_token(sandbox: "SandboxBase", repository: str, github_token: str) -> bool:
    """Rewrite ``origin``'s remote URL with a fresh ``x-access-token``.

    Takes effect immediately — git re-reads ``.git/config`` on every operation,
    so this fixes ``git fetch``/``push`` even mid-turn. Guards on ``.git`` so it
    no-ops when the snapshot predates the clone.
    """
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
    """Replace specific keys in the agentsh env file, preserving all other entries.

    The env file is a NUL-delimited ``key=value`` list that the agentsh exec
    wrapper re-sources on every command, so updating it here propagates fresh
    tokens to the agent's subsequent ``gh``/``git`` invocations without a reboot.
    Read-modify-write (via base64 to survive NUL bytes) so we never clobber the
    rest of the captured environment.
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

        token = get_sandbox_github_token(
            ctx.github_integration_id,
            run_id=ctx.run_id,
            state=ctx.state,
            task=task,
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


def build_sandbox_credentials(ctx: "TaskProcessingContext") -> list[SandboxCredential]:
    credentials: list[SandboxCredential] = []
    if ctx.has_github_credentials:
        credentials.append(GitHubSandboxCredential())
    return credentials
