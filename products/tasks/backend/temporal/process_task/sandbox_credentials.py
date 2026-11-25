"""Refresh long-lived credentials inside a running task sandbox by re-resolving and re-applying tokens in place."""

import shlex
import logging
import textwrap
import contextlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Protocol

from django.db import transaction

import redis

from posthog.egress.limiter.policies import Priority
from posthog.integrations import IntegrationNotFound
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration, UserIntegration
from posthog.redis import get_client

from products.tasks.backend.constants import DEFAULT_SANDBOX_WORKING_DIR, GITLAB_HOST, SANDBOX_REPOSITORIES_ROOT
from products.tasks.backend.exceptions import CredentialUnavailableError, SandboxExecutionError
from products.tasks.backend.logic.services.agentsh import ENV_FILE, GITHUB_ENV_FILE, OAUTH_ENV_FILE
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
CREDENTIAL_SANDBOX_EXEC_TIMEOUT_SECONDS = 15
GITHUB_REMOTE_SCRUB_TIMEOUT_SECONDS = 60
DEFAULT_SANDBOX_HOME = "/root"


def github_refresh_interval_seconds(token: str) -> float:
    for prefix, interval in _GITHUB_REFRESH_INTERVAL_BY_PREFIX.items():
        if token.startswith(prefix):
            return interval
    return DEFAULT_REFRESH_INTERVAL_SECONDS


def set_git_remote_token(
    sandbox: "SandboxBase", repository: str, github_token: str | None, *, gitlab_token: str | None = None
) -> bool:
    """Rewrite ``origin`` with the current credential state; git re-reads it on every operation."""
    repo_path = f"{SANDBOX_REPOSITORIES_ROOT}/{repository.lower()}"
    if gitlab_token:
        remote_url = f"https://oauth2:{gitlab_token}@{GITLAB_HOST}/{repository.lower()}.git"
    elif github_token:
        remote_url = f"https://x-access-token:{github_token}@github.com/{repository}.git"
    else:
        remote_url = f"https://github.com/{repository}.git"
    update_remote = (
        f"if [ -d {shlex.quote(repo_path + '/.git')} ]; then "
        f"cd {shlex.quote(repo_path)} && "
        f"git remote set-url origin {shlex.quote(remote_url)}; "
        f"fi"
    )
    result = sandbox.execute(update_remote, timeout_seconds=CREDENTIAL_SANDBOX_EXEC_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        logger.warning(
            "Failed to refresh git remote URL",
            extra={"sandbox_id": sandbox.id, "repository": repository, "stderr": result.stderr},
        )
        return False
    return True


def _write_sandbox_credential_file(sandbox: "SandboxBase", path: str, payload: bytes) -> bool:
    """Atomically replace one credential domain without a cross-key read-modify-write."""
    write = sandbox.write_file(path, payload, timeout_seconds=CREDENTIAL_SANDBOX_EXEC_TIMEOUT_SECONDS)
    if write.exit_code != 0:
        if write.error in {"exec_write", "atomic_move"}:
            raise SandboxExecutionError(
                "Failed to write sandbox credential file",
                {
                    "sandbox_id": sandbox.id,
                    "path": path,
                    "write_stage": write.error,
                    "exit_code": write.exit_code,
                },
                cause=RuntimeError(f"Sandbox credential write exited with code {write.exit_code}"),
            )
        logger.warning(
            "Failed to refresh sandbox credential file",
            extra={"sandbox_id": sandbox.id, "credential_file": path, "stderr": write.stderr},
        )
        return False

    chmod = sandbox.execute(f"chmod 600 {shlex.quote(path)}", timeout_seconds=CREDENTIAL_SANDBOX_EXEC_TIMEOUT_SECONDS)
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


def apply_github_credentials_to_sandbox(sandbox: "SandboxBase", repositories: Sequence[str], github_token: str) -> bool:
    """Re-inject a GitHub token into both places a running sandbox reads it from.

    Every clone embeds the token in its own ``origin``, so each of ``repositories`` is rewritten;
    a run that cloned several and refreshed only one keeps an expired token in the others.
    Returns ``True`` only when every applicable write succeeded. A caller enforcing per-actor
    identity must treat a partial write as an unconfirmed rebind: leaving one location on the
    previous actor's token would let a follow-up actor act as them.
    """
    # A list, not a generator: every remote gets rewritten even after one fails, so a partial
    # failure never leaves a later checkout on the old token.
    remote_results = [set_git_remote_token(sandbox, repository, github_token) for repository in repositories]
    remote_applied = all(remote_results)
    github_payload = b"".join(f"{key}={github_token}\x00".encode() for key in GITHUB_ENV_KEYS)
    env_applied = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, github_payload)
    return remote_applied and env_applied


def clear_github_credentials_from_sandbox(sandbox: "SandboxBase", repositories: Sequence[str]) -> bool:
    """Log the sandbox out of GitHub: strip the token from every git remote and blank the GitHub
    credential file, so a follow-up actor who lacks access can't reuse the previous actor's token.
    Returns ``True`` only when all were cleared.
    """
    remote_results = [set_git_remote_token(sandbox, repository, None) for repository in repositories]
    remote_cleared = all(remote_results)
    env_cleared = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, b"")
    return remote_cleared and env_cleared


def clear_github_remotes_from_sandbox(sandbox: "SandboxBase") -> bool:
    """Remove GitHub credentials from the restored workspace and effective Git config sources."""
    script = textwrap.dedent("""\
        import glob
        import os
        import re
        import shlex
        import subprocess
        import sys
        from urllib.parse import urlsplit

        root = os.path.realpath(sys.argv[1])
        env_file = sys.argv[2]
        default_home = sys.argv[3]
        git = "/usr/bin/git"
        git_env = {
            "HOME": default_home,
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        github_host_pattern = re.compile(
            rb"(?i)(?<![a-z0-9-])(?:[a-z0-9-]+\\.)*github\\.com\\.?(?=[:/?#=]|\\.extraheader(?:=|$)|$)"
        )
        credential_url_pattern = re.compile(rb"(?i)[a-z][a-z0-9+.-]*://([^/@\\s]+)@([^/?#\\s]+)")
        config_paths = []
        queued_configs = set()
        visited_configs = set()
        credential_files = set()
        repository_roots = set()

        def fail(error):
            raise error

        def read_env_file():
            try:
                with open(env_file, "rb") as handle:
                    raw = handle.read()
            except FileNotFoundError:
                return {}, b""
            values = {}
            entries = []
            for entry in raw.split(b"\\0"):
                if not entry:
                    continue
                key, separator, value = entry.partition(b"=")
                if separator:
                    values[os.fsdecode(key)] = os.fsdecode(value)
                    entries.append((key, value))
            return values, b"\\0".join(key + b"=" + value for key, value in entries) + (b"\\0" if entries else b"")

        def expand_path(value, base):
            value = os.path.expanduser(value)
            if not os.path.isabs(value):
                value = os.path.join(base, value)
            return os.path.abspath(value)

        def add_config(path):
            if not path:
                return
            path = os.path.abspath(path)
            if not os.path.exists(path):
                return
            if not os.path.isfile(path):
                raise RuntimeError("Git config path is not a file")
            real_path = os.path.realpath(path)
            if real_path not in queued_configs and real_path not in visited_configs:
                queued_configs.add(real_path)
                config_paths.append(path)

        def github_host(host):
            host = host.lower().rstrip(".")
            return host == "github.com" or host.endswith(".github.com")

        def has_github_host(value):
            return github_host_pattern.search(value) is not None

        def has_github_credentials(value):
            for match in credential_url_pattern.finditer(value):
                authority = match.group(2).split(b"/", 1)[0]
                host = authority.rsplit(b"@", 1)[-1].split(b":", 1)[0].decode("ascii", "ignore")
                if github_host(host) and not (value[match.start() :].lower().startswith(b"ssh://git@")):
                    return True
            return False

        def strip_github_userinfo(value):
            match = re.match(rb"(?i)^([a-z][a-z0-9+.-]*://)([^/@\\s]+@)([^/?#\\s]+)(.*)$", value)
            if not match:
                return value
            scheme, userinfo, authority, suffix = match.groups()
            host = authority.split(b":", 1)[0].decode("ascii", "ignore")
            if not github_host(host):
                return value
            if scheme.lower() == b"ssh://" and userinfo.lower() == b"git@":
                return value
            return scheme + authority + suffix

        def is_helper_key(key):
            key = key.lower()
            return key == b"credential.helper" or (key.startswith(b"credential.") and key.endswith(b".helper"))

        def is_github_helper_key(key):
            lower_key = key.lower()
            if not is_helper_key(lower_key):
                return False
            if lower_key == b"credential.helper" or b"*" in lower_key:
                return True
            scope = lower_key[len(b"credential.") : -len(b".helper")]
            return has_github_host(scope)

        def add_store_path(path, config_path, homes):
            path = os.path.expanduser(path)
            if os.path.isabs(path):
                credential_files.add(os.path.abspath(path))
                return
            bases = [os.path.dirname(config_path), root, *repository_roots, *homes]
            credential_files.update(os.path.abspath(os.path.join(base, path)) for base in bases)

        def collect_helper_store(value, config_path, homes):
            try:
                parts = shlex.split(os.fsdecode(value))
            except ValueError:
                return False
            if not parts or os.path.basename(parts[0]) not in ("store", "git-credential-store"):
                return False
            store_path = None
            index = 1
            while index < len(parts):
                part = parts[index]
                if part.startswith("--file="):
                    store_path = part.partition("=")[2]
                    break
                if part == "--file" and index + 1 < len(parts):
                    store_path = parts[index + 1]
                    break
                index += 1
            if store_path:
                add_store_path(store_path, config_path, homes)
            else:
                credential_files.update(os.path.join(home, ".git-credentials") for home in homes)
            return True

        def collect_gitdir(path):
            path = os.path.realpath(path)
            pending = [path]
            seen = set()
            while pending:
                gitdir = pending.pop()
                if gitdir in seen:
                    continue
                seen.add(gitdir)
                if not os.path.isdir(gitdir):
                    raise RuntimeError("Git checkout points to a missing git directory")
                add_config(os.path.join(gitdir, "config"))
                add_config(os.path.join(gitdir, "config.worktree"))
                common_file = os.path.join(gitdir, "commondir")
                if os.path.isfile(common_file):
                    with open(common_file, "rb") as handle:
                        common = os.fsdecode(handle.read().strip())
                    if common:
                        pending.append(expand_path(common, gitdir))
                for child_name in ("modules", "worktrees"):
                    child_root = os.path.join(gitdir, child_name)
                    if os.path.isdir(child_root):
                        for child in os.scandir(child_root):
                            if child.is_dir(follow_symlinks=True):
                                pending.append(child.path)

        def collect_gitfile(path, worktree):
            with open(path, "rb") as handle:
                value = os.fsdecode(handle.read().strip())
            if not value.lower().startswith("gitdir:"):
                raise RuntimeError("Invalid .git file in restored workspace")
            gitdir = expand_path(value.partition(":")[2].strip(), worktree)
            collect_gitdir(gitdir)

        git_prefix_path = [None]

        def add_include(config_path, value):
            include = os.fsdecode(value)
            if not include:
                return
            prefix_marker = "%(prefix)/"
            if include.startswith(prefix_marker):
                if git_prefix_path[0] is None:
                    result = subprocess.run([git, "--exec-path"], cwd="/", env=git_env, capture_output=True)
                    result.check_returncode()
                    git_exec_path = os.path.realpath(os.fsdecode(result.stdout.strip()))
                    git_prefix_path[0] = os.path.dirname(os.path.dirname(git_exec_path))
                include = os.path.join(git_prefix_path[0], include[len(prefix_marker) :])
            include_path = expand_path(include, os.path.dirname(config_path))
            matches = glob.glob(include_path) if glob.has_magic(include_path) else [include_path]
            for match in matches:
                add_config(match)

        def run_git_config(config_path, *args):
            result = subprocess.run(
                [git, "config", "--file", config_path, "--no-includes", *args],
                cwd="/",
                env=git_env,
                capture_output=True,
            )
            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, result.args)
            return result.stdout

        def read_config(config_path):
            output = run_git_config(config_path, "--null", "--list")
            entries = []
            for entry in output.split(b"\\0"):
                if entry:
                    key, _, value = entry.partition(b"\\n")
                    entries.append((key, value))
            return entries

        def config_include(key):
            key = key.lower()
            return key.endswith(b".path") and (key.startswith(b"include.") or key.startswith(b"includeif."))

        def sanitize_config(config_path, entries, homes):
            remove_keys = set()
            rewritten = {}
            for key, value in entries:
                lower_key = key.lower()
                if config_include(key):
                    add_include(config_path, value)
                if is_helper_key(key):
                    is_store_helper = collect_helper_store(value, config_path, homes)
                    if is_github_helper_key(key) and not (lower_key == b"credential.helper" and is_store_helper):
                        remove_keys.add(key)
                if lower_key == b"http.extraheader" or (
                    lower_key.startswith(b"http.")
                    and lower_key.endswith(b".extraheader")
                    and (has_github_host(key) or b"*" in key)
                ):
                    remove_keys.add(key)
                if lower_key.startswith(b"url.") and lower_key.endswith((b".insteadof", b".pushinsteadof")):
                    if has_github_host(key) or has_github_host(value) or has_github_credentials(key) or has_github_credentials(value):
                        remove_keys.add(key)
                if (lower_key.startswith(b"remote.") and lower_key.endswith((b".url", b".pushurl"))) or (
                    lower_key.startswith(b"submodule.") and lower_key.endswith(b".url")
                ):
                    rewritten.setdefault(key, []).append(strip_github_userinfo(value))

            for key in remove_keys:
                run_git_config(config_path, "--unset-all", os.fsdecode(key))
            for key, values in rewritten.items():
                original_values = [original for entry_key, original in entries if entry_key == key]
                if values == original_values:
                    continue
                run_git_config(config_path, "--unset-all", os.fsdecode(key))
                for value in values:
                    run_git_config(config_path, "--add", os.fsdecode(key), os.fsdecode(value))

        def scrub_credential_file(path):
            path = os.path.realpath(path)
            if not os.path.isfile(path):
                return
            with open(path, "rb") as handle:
                raw = handle.read()
            lines = raw.splitlines(keepends=True)
            kept = []
            changed = False
            for line in lines:
                candidate = line.strip()
                try:
                    host = urlsplit(os.fsdecode(candidate)).hostname
                except ValueError:
                    host = None
                if (host and github_host(host)) or (not host and b"github.com" in candidate.lower()):
                    changed = True
                else:
                    kept.append(line)
            if changed:
                temporary = path + ".credential-scrub"
                with open(temporary, "wb") as handle:
                    handle.write(b"".join(kept))
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)

        persisted_env, cleaned_env = read_env_file()
        homes = {os.path.realpath(default_home)}
        for value in (persisted_env.get("HOME"), os.environ.get("HOME")):
            if value:
                homes.add(os.path.realpath(expand_path(value, default_home)))
        xdg_dirs = set()
        for value in (persisted_env.get("XDG_CONFIG_HOME"), os.environ.get("XDG_CONFIG_HOME")):
            if value:
                xdg_dirs.add(os.path.realpath(expand_path(value, default_home)))
        xdg_dirs.update(os.path.join(home, ".config") for home in homes)
        for home in homes:
            add_config(os.path.join(home, ".gitconfig"))
            add_config(os.path.join(home, ".config", "git", "config"))
            credential_files.add(os.path.join(home, ".git-credentials"))
        for xdg_dir in xdg_dirs:
            add_config(os.path.join(xdg_dir, "git", "config"))
            credential_files.add(os.path.join(xdg_dir, "git", "credentials"))
        add_config("/etc/gitconfig")
        for name in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            value = persisted_env.get(name) or os.environ.get(name)
            if value and value != "/dev/null":
                add_config(expand_path(value, default_home))
        gh_config_dirs = {os.path.join(xdg, "gh") for xdg in xdg_dirs}
        for value in (persisted_env.get("GH_CONFIG_DIR"), os.environ.get("GH_CONFIG_DIR")):
            if value:
                gh_config_dirs.add(expand_path(value, default_home))

        if os.path.isdir(root):
            for directory, dirs, files in os.walk(root, topdown=True, onerror=fail):
                if ".git" in dirs:
                    repository_roots.add(directory)
                    collect_gitdir(os.path.join(directory, ".git"))
                    dirs.remove(".git")
                if ".git" in files:
                    repository_roots.add(directory)
                    collect_gitfile(os.path.join(directory, ".git"), directory)
                if ".gitmodules" in files:
                    add_config(os.path.join(directory, ".gitmodules"))
                if "HEAD" in files and "config" in files and {"objects", "refs"}.issubset(dirs):
                    repository_roots.add(directory)
                    collect_gitdir(directory)
                    dirs[:] = [name for name in dirs if name in ("modules", "worktrees")]

        while config_paths:
            config_path = config_paths.pop()
            real_path = os.path.realpath(config_path)
            if real_path in visited_configs:
                continue
            visited_configs.add(real_path)
            sanitize_config(config_path, read_config(config_path), homes)

        for path in credential_files:
            scrub_credential_file(path)
        for directory in gh_config_dirs:
            hosts_file = os.path.join(directory, "hosts.yml")
            if os.path.lexists(hosts_file):
                os.remove(os.path.realpath(hosts_file))

        kept_env = []
        for entry in cleaned_env.split(b"\\0"):
            if not entry:
                continue
            key = entry.partition(b"=")[0]
            if key in (b"GH_TOKEN", b"GITHUB_TOKEN") or key.startswith(b"GIT_CONFIG_"):
                continue
            kept_env.append(entry)
        cleaned_env = b"\\0".join(kept_env) + (b"\\0" if kept_env else b"")
        try:
            with open(env_file, "rb") as handle:
                original_env = handle.read()
        except FileNotFoundError:
            original_env = b""
        if cleaned_env != original_env and os.path.exists(env_file):
            target = os.path.realpath(env_file)
            temporary = target + ".credential-scrub"
            with open(temporary, "wb") as handle:
                handle.write(cleaned_env)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
    """)
    command = (
        f"/usr/bin/python3 -I -c {shlex.quote(script)} "
        f"{shlex.quote(DEFAULT_SANDBOX_WORKING_DIR)} {shlex.quote(ENV_FILE)} {shlex.quote(DEFAULT_SANDBOX_HOME)}"
    )
    result = sandbox.execute(command, timeout_seconds=GITHUB_REMOTE_SCRUB_TIMEOUT_SECONDS)
    if result.exit_code != 0:
        logger.warning(
            "Failed to scrub GitHub credentials from sandbox config",
            extra={"sandbox_id": sandbox.id, "stderr": result.stderr},
        )
        return False
    return True


def clear_github_env_from_gitlab_sandbox(sandbox: "SandboxBase") -> bool:
    """Clear GitHub credentials while retaining GitLab remote URLs."""
    configs_cleared = clear_github_remotes_from_sandbox(sandbox)
    env_cleared = _write_sandbox_credential_file(sandbox, GITHUB_ENV_FILE, b"")
    return configs_cleared and env_cleared


def _loop_owner_credentials_revoked(task: Task, state: dict | None) -> bool:
    """Whether a persisted legacy loop run's owner may still receive credentials."""
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


def _actor_rebound_away_from(sandbox_id: str, permitted_session_user_id: int | None) -> int | None:
    """The actor a per-message transition rebound (or logged out) this sandbox to, when that differs
    from the identity the caller may write for (else ``None``). Writing a token over a session
    bound to someone else would resurrect that identity for the current actor — callers skip when
    this returns a value. Distinct from `_loop_owner_credentials_revoked`, which gates on owner
    *eligibility* rather than session rebind."""
    bound_actor = get_sandbox_github_identity_user(sandbox_id)
    return bound_actor if bound_actor is not None and bound_actor != permitted_session_user_id else None


# TTL derivation: the lock must outlive the whole critical section, or the lease can expire mid-write
# and let a concurrent refresh acquire and interleave (a regression we hit before). Each managed
# write is a chain of in-sandbox execs, each bounded by a 15s timeout — set_git_remote_token (1 exec)
# and _write_sandbox_credential_file (a write, move, and chmod). The per-message gate can run two
# such chains back-to-back in one lock hold (apply the new token, then, if that fails, log out), so
# the worst case is ~8 × 15s ≈ 2 min. A 5 min TTL clears that with margin; recompute if those exec
# timeouts change. The wait stays under the refresh activity's 2 min timeout, so a contender that
# can't acquire skips (fail-safe) rather than blocking the activity.
_CREDENTIAL_LOCK_TTL_SECONDS = 5 * 60
_CREDENTIAL_LOCK_WAIT_SECONDS = 15


def _sandbox_credential_lock_key(sandbox_id: str) -> str:
    return f"tasks:sandbox_github_creds:{sandbox_id}"


@contextlib.contextmanager
def _redis_lock(key: str, *, ttl: int, wait: int) -> Iterator[bool]:
    """Acquire a redis lock, yielding whether it was obtained; release only if held.

    Swallows a release-time ``LockError`` so an already-expired lock never crashes the caller."""
    lock = get_client().lock(key, timeout=ttl, blocking_timeout=wait)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.exceptions.LockError:
                logger.warning("redis_lock_release_failed", extra={"lock_key": key})


@contextlib.contextmanager
def sandbox_credential_lock(sandbox_id: str) -> Iterator[bool]:
    """Serialize every writer of one sandbox's GitHub credentials — scheduled refresh, sibling
    propagation, and the per-message actor gate — so their check → write → marker-update runs
    atomically. Without it, a slow owner-token write can land *after* a follow-up rebound the sandbox
    to a different actor, resurrecting the owner's identity for the current actor. Yields whether the
    lock was acquired; a caller that does not get it must skip the write rather than race."""
    with _redis_lock(
        _sandbox_credential_lock_key(sandbox_id), ttl=_CREDENTIAL_LOCK_TTL_SECONDS, wait=_CREDENTIAL_LOCK_WAIT_SECONDS
    ) as acquired:
        yield acquired


def _is_gitlab_task(task_id: str) -> bool:
    return Task.objects.filter(id=task_id, repository_integration_id__isnull=False).exists()


def _apply_token_locked(
    sandbox: "SandboxBase",
    repositories: Sequence[str],
    token: str,
    run_id: str,
    permitted_session_user_id: int | None,
    *,
    task_id: str,
) -> bool:
    """Apply a token only while the sandbox's session still belongs to the permitted identity.

    Resolving a token can take seconds against GitHub's API. Serializing the re-check and the write
    under the per-sandbox lock closes the window where a per-message transition rebinds the sandbox
    between the caller's earlier check and this write. Returns ``True`` only when the token was
    actually applied."""
    with sandbox_credential_lock(sandbox.id) as acquired:
        if not acquired:
            logger.warning("token_apply_skipped_lock_unavailable", extra={"run_id": run_id, "sandbox_id": sandbox.id})
            return False
        # A GitLab turn clears GitHub credentials under this same lock, so a task that moved to
        # GitLab is checked here rather than under a task row lock held across the sandbox write.
        if _is_gitlab_task(task_id):
            logger.info("token_apply_skipped_gitlab_task", extra={"run_id": run_id, "sandbox_id": sandbox.id})
            return False
        rebound_actor = _actor_rebound_away_from(sandbox.id, permitted_session_user_id)
        if rebound_actor is not None:
            logger.info(
                "token_apply_skipped_actor_transition",
                extra={
                    "run_id": run_id,
                    "bound_actor": rebound_actor,
                    "permitted_session_user": permitted_session_user_id,
                },
            )
            return False
        return apply_github_credentials_to_sandbox(sandbox, repositories, token)


USER_TOKEN_REFRESH_INTERVAL_SECONDS: float = _GITHUB_REFRESH_INTERVAL_BY_PREFIX["ghu_"]
# TTL covers a slow mint + propagation; wait stays under the refresh activity's 2 min timeout.
_ROTATION_LOCK_TTL_SECONDS = 120
_ROTATION_LOCK_WAIT_SECONDS = 90


def _rotation_lock_key(user_integration_id: int) -> str:
    return f"tasks:gh_user_token_rotate:{user_integration_id}"


class LiveSandbox(NamedTuple):
    """A live sandbox eligible for owner-token propagation, with the ``owner_id`` the
    per-sandbox actor-rebind re-check needs carried alongside."""

    run_id: str
    sandbox_id: str
    repository: str | None
    owner_id: int | None
    task_id: str


def _live_sandboxes_for_user_integration(user_integration_id: int) -> list[LiveSandbox]:
    rows: list[LiveSandbox] = []
    runs = TaskRun.objects.filter(
        status=TaskRun.Status.IN_PROGRESS,
        task__github_user_integration_id=user_integration_id,
        task__repository_integration_id__isnull=True,
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
        if (run.state or {}).get("github_token_scope"):
            continue
        state = run.state or {}
        if is_slack_interaction_state(state) and "slack_actor_user_id" in state:
            actor_user_id = state["slack_actor_user_id"]
            if (
                not isinstance(actor_user_id, int)
                or isinstance(actor_user_id, bool)
                or actor_user_id != run.task.created_by_id
            ):
                # This integration belongs to the task creator. Never propagate their rotating
                # token into a Slack run that another member is steering.
                continue
        elif is_slack_interaction_state(state):
            # An unstamped Slack run has no durable proof that its current actor is the creator.
            # Keep the owner token out until a follow-up persists its actor before delivery.
            continue
        if _loop_owner_credentials_revoked(run.task, run.state):
            continue
        # This loop carries the owner's token; skip a sandbox a per-message transition rebound to
        # a different actor, or re-applying it would resurrect the owner's identity for that actor.
        if _actor_rebound_away_from(sandbox_id, run.task.created_by_id) is not None:
            continue
        rows.append(LiveSandbox(str(run.id), sandbox_id, run.task.repository, run.task.created_by_id, str(run.task_id)))
    return rows


def _propagate_user_token(user_integration_id: int, token: str) -> int:
    from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id  # noqa: PLC0415

    applied = 0
    for live in _live_sandboxes_for_user_integration(user_integration_id):
        try:
            sandbox = get_sandbox_class_for_sandbox_id(live.sandbox_id).get_by_id(live.sandbox_id)
            # Re-check the actor binding under the per-sandbox lock: the filter above is not atomic
            # with this write, so a transition could have rebound the sandbox in between.
            if sandbox.is_running() and _apply_token_locked(
                sandbox,
                [live.repository] if live.repository else [],
                token,
                live.run_id,
                live.owner_id,
                task_id=live.task_id,
            ):
                applied += 1
        except Exception:
            logger.warning(
                "Failed to propagate refreshed GitHub user token to sibling sandbox",
                extra={"integration_id": user_integration_id, "run_id": live.run_id, "sandbox_id": live.sandbox_id},
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
    with _redis_lock(
        _rotation_lock_key(integration_id), ttl=_ROTATION_LOCK_TTL_SECONDS, wait=_ROTATION_LOCK_WAIT_SECONDS
    ) as acquired:
        if not acquired:
            # Waited out the budget — read the current token without minting; the holder's propagation self-heals.
            integration.integration.refresh_from_db()
            return UserGitHubIntegration(
                integration.integration, source="tasks_sandbox", priority=Priority.CRITICAL
            ).user_access_token

        integration.integration.refresh_from_db()
        current = UserGitHubIntegration(integration.integration, source="tasks_sandbox", priority=Priority.CRITICAL)
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


# Mutable on purpose: the `SandboxCredential` Protocol below declares `kind` as a settable
# variable, which a frozen dataclass cannot satisfy.
@dataclass(frozen=False)
class GitHubSandboxCredential:
    """Refreshes the GitHub token (user *or* installation, per authorship)."""

    kind: str = "github"

    def refresh(self, sandbox: "SandboxBase", ctx: "TaskProcessingContext", task: Task) -> CredentialRefreshOutcome:
        # A run that started on GitHub keeps this credential in its context after the task moves to
        # GitLab, and a GitLab sandbox must not get a GitHub token back.
        if task.repository_integration_id is not None:
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )
        # A read-only run must stay read-only for its whole lifetime: without this guard the
        # periodic refresh would resolve the full credential path (the team integration is
        # attached to every task) and silently swap the downscoped token for the write-capable
        # one mid-run. This holds for a run that cloned repositories too, because the pinned
        # repositories decide what the sandbox can read, never what it can write. Re-mint the same
        # read-only grant instead; best-effort like the original.
        if ctx.github_read_access:
            token = get_readonly_github_token(ctx.team_id, repositories=ctx.repositories)
            if token and _loop_owner_credentials_revoked(task, ctx.state):
                token = None
            if token:
                # Pass the run's repositories so that every cloned checkout's `origin` is
                # rewritten with the fresh token, not just the credential file. A repo-less run has
                # no remote to rewrite, but a repo-backed one keeps the expired token in
                # `.git/config` without this, which fails every later `git fetch`.
                apply_github_credentials_to_sandbox(sandbox, ctx.repositories, token)
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

        # Gate on the session this refresh may land a token in, not the run owner: on a thread
        # that passed to someone else they are not the same person. A sandbox that already
        # belongs to a third party is left alone before any unresolved actor is reported, since
        # nothing would be minted for it either way.
        actor_user = get_task_run_credential_user(task, ctx.state)
        permitted_session_user_id = actor_user.id if actor_user is not None else None
        rebound_actor = _actor_rebound_away_from(sandbox.id, permitted_session_user_id)
        if rebound_actor is not None:
            logger.info(
                "github_refresh_skipped_actor_transition",
                extra={
                    "run_id": ctx.run_id,
                    "bound_actor": rebound_actor,
                    "permitted_session_user": permitted_session_user_id,
                },
            )
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )

        if is_slack_interaction_state(ctx.state) and actor_user is None:
            raise ReauthorizationRequired("Slack run requires an acting user before refreshing GitHub credentials.")

        integration = None
        if (
            ctx.github_token_scope is None
            and get_pr_authorship_mode(task, ctx.state) == PrAuthorshipMode.USER
            and not is_caller_token_run(ctx.run_id, ctx.state)
        ):
            integration = resolve_user_github_integration_for_task(
                task,
                actor_user=actor_user,
                repository=ctx.repository,
                allow_refresh=True,
            )

        if integration is not None:
            return self._refresh_shared_user_integration(sandbox, ctx, task, integration, permitted_session_user_id)

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
        except (IntegrationNotFound, UserIntegration.DoesNotExist) as e:
            raise CredentialUnavailableError(
                "GitHub integration for this run no longer exists",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=e,
            )
        except ReauthorizationRequired as e:
            # On a Slack run the failure belongs to the current actor, not to the run. The next
            # message can come from an actor who has access, and the per-message rebind then
            # applies their token. An orphaned kind stays excluded until the sandbox goes, so
            # skip this refresh and keep the loop alive to refresh that token later.
            if is_slack_interaction_state(ctx.state):
                logger.info(
                    "github_refresh_skipped_actor_without_access",
                    extra={"run_id": ctx.run_id, "actor": permitted_session_user_id},
                )
                return CredentialRefreshOutcome(
                    self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
                )
            raise CredentialUnavailableError(
                "GitHub user integration for this run requires reauthorization",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=e,
            )
        if not token:
            return CredentialRefreshOutcome(
                self.kind, refreshed=False, next_refresh_seconds=DEFAULT_REFRESH_INTERVAL_SECONDS
            )

        applied = _apply_token_locked(
            sandbox, ctx.repositories, token, ctx.run_id, permitted_session_user_id, task_id=ctx.task_id
        )
        return CredentialRefreshOutcome(
            self.kind, refreshed=applied, next_refresh_seconds=github_refresh_interval_seconds(token)
        )

    def _refresh_shared_user_integration(
        self,
        sandbox: "SandboxBase",
        ctx: "TaskProcessingContext",
        task: Task,
        integration: UserGitHubIntegration,
        permitted_session_user_id: int | None,
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
            # An installation token is the team's, not a person's, so it may only land in the
            # owner's own session, never in that of someone whose personal token just failed.
            applied = _apply_token_locked(
                sandbox, ctx.repositories, fallback, ctx.run_id, task.created_by_id, task_id=ctx.task_id
            )
            return CredentialRefreshOutcome(
                self.kind, refreshed=applied, next_refresh_seconds=github_refresh_interval_seconds(fallback)
            )
        if token and _loop_owner_credentials_revoked(task, ctx.state):
            token = None
        applied = (
            _apply_token_locked(
                sandbox, ctx.repositories, token, ctx.run_id, permitted_session_user_id, task_id=ctx.task_id
            )
            if token
            else False
        )
        return CredentialRefreshOutcome(
            self.kind, refreshed=applied, next_refresh_seconds=USER_TOKEN_REFRESH_INTERVAL_SECONDS
        )

    def _installation_token_fallback(self, ctx: "TaskProcessingContext", task: Task, cause: Exception) -> str | None:
        if task.github_integration_id is None:
            raise CredentialUnavailableError(
                "GitHub user integration requires reauthorization and no team installation is available",
                {"run_id": ctx.run_id, "task_id": ctx.task_id},
                cause=cause,
            )
        try:
            return get_github_token(
                task.team_id, task.github_integration_id, repositories=ctx.github_access_repositories
            )
        except IntegrationNotFound as e:
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
