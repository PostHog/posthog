"""Mutagen CLI wrapper for one-way local->remote file sync.

Mirrors ``coder.py`` shape: a managed binary lives in ``~/.hogli/bin/``,
version is pinned, and all subprocess interactions are isolated behind thin
wrappers. v1 only targets Coder workspaces as the remote endpoint.
"""

from __future__ import annotations

import os
import re
import json
import shutil
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Any

import click

from .coder import _fail

_MANAGED_MUTAGEN_DIR = Path.home() / ".hogli" / "bin"
_MUTAGEN_VERSION = "0.18.1"

# mutagen hardcodes `-oServerAliveInterval=10 -oServerAliveCountMax=1` onto every
# ssh command line it builds, and a command-line `-o` overrides ~/.ssh/config, so
# the keepalive cannot be relaxed via config. One missed keepalive (interval x
# count = 10s of silence) tears the connection down -- which is exactly what
# happens when a devbox's Tailscale path flaps to a DERP relay (it resets the
# direct path roughly every 26s) mid-sync, surfacing as a "broken pipe" at the
# staging step and a sync that loops forever without ever reaching `watching`.
# We can't change the constant, but we can interpose an ssh that rewrites it for
# devbox connections: a shim on MUTAGEN_SSH_PATH bumps the count so the
# connection rides out a reset window. _KEEPALIVE_COUNT x interval(10s) is the
# resulting silence tolerance (~30s, comfortably past the ~26s reset cadence).
_SSH_SHIM_DIR = Path.home() / ".hogli" / "mutagen-ssh-shim"
_KEEPALIVE_COUNT = 3

# Baked at generation time (see ensure_ssh_shim): only when the ssh/scp target is
# a devbox (a `coder.*` host -- the sole thing hogli syncs to) do we bump
# mutagen's count; every other invocation passes through untouched, so a shared
# daemon's non-devbox syncs are unaffected. Execs the real ssh/scp by absolute
# path so a shim-dir entry on PATH can never make the shim re-invoke itself.
_SHIM_TEMPLATE = """#!/usr/bin/env bash
# Managed by hogli (`hogli devbox:sync`) -- do not edit; regenerated on sync.
# Raises mutagen's intolerant `-oServerAliveCountMax=1` for devbox (coder.*)
# connections so the sync survives a Tailscale/DERP path reset instead of dying
# with a broken pipe. Any non-devbox ssh is passed through unchanged.
devbox=
for a in "$@"; do
  case "$a" in coder.*|*@coder.*) devbox=1 ;; esac
done
args=()
for a in "$@"; do
  case "$a" in
  -oServerAliveCountMax=*) [ -n "$devbox" ] && a="-oServerAliveCountMax={count}" ;;
  esac
  args+=("$a")
done
exec "{real}" ${{args[@]+"${{args[@]}}"}}
"""
_RELEASE_URL_TEMPLATE = (
    "https://github.com/mutagen-io/mutagen/releases/download/v{version}/mutagen_{os}_{arch}_v{version}.tar.gz"
)

# Pinned SHA256 of each release tarball, from the v0.18.1 `SHA256SUMS` asset.
# The download is unverified TLS-only without this, so a MITM or tampered
# release could execute arbitrary code on the engineer's machine on every sync.
# Bump these in lockstep with `_MUTAGEN_VERSION`.
_MUTAGEN_SHA256 = {
    ("darwin", "amd64"): "7d06f7d8fcfe90bc7e55cc834a2f2f20c2e0af9ea9bc35911fc4341ad56a9bbf",
    ("darwin", "arm64"): "6f810416d9e5fc4fd5e18431146f8b3c5a2056ba5a24f76c1e66da86eb3257e2",
    ("linux", "amd64"): "7735286c778cc438418209f24d03a64f3a0151c8065ef0fe079cfaf093af6f8f",
    ("linux", "arm64"): "bcba735aebf8cbc11da9b3742118a665599ac697fa06bc5751cac8dcd540db8a",
}


def _mutagen_platform() -> tuple[str, str]:
    """Map the host to mutagen's ``(os, arch)`` release naming, or fail if unsupported.

    ``os`` is ``darwin``/``linux`` and ``arch`` is ``amd64``/``arm64``.
    Verified against the v0.18.1 release on GitHub.
    """
    system = platform.system().lower()
    if system not in ("darwin", "linux"):
        _fail(f"Unsupported OS for mutagen install: {system}. hogli devbox:sync supports macOS and Linux only.")

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        _fail(f"Unsupported CPU arch for mutagen install: {machine}. hogli devbox:sync supports amd64 and arm64 only.")

    return system, arch


def _mutagen_release_url(version: str = _MUTAGEN_VERSION) -> str:
    """Build the GitHub release tarball URL for the current platform."""
    system, arch = _mutagen_platform()
    return _RELEASE_URL_TEMPLATE.format(version=version, os=system, arch=arch)


def _mutagen_bin() -> str:
    """Return the path to the hogli-managed mutagen binary, falling back to PATH."""
    managed = _MANAGED_MUTAGEN_DIR / "mutagen"
    if managed.is_file():
        return str(managed)
    return shutil.which("mutagen") or "mutagen"


def _mutagen_env() -> dict[str, str]:
    """Process env for mutagen calls, pinning ssh resolution to the keepalive shim.

    Setting ``MUTAGEN_SSH_PATH`` here means any daemon mutagen *auto-starts* as a
    child of this process inherits it (the only env channel that reaches the
    daemon -- see ``ensure_daemon_with_shim``). Pointing at the dir is safe even
    before the shim exists: mutagen just falls back to a PATH ssh.
    """
    return {**os.environ, "MUTAGEN_SSH_PATH": str(_SSH_SHIM_DIR)}


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a mutagen subprocess with consistent text handling.

    A leading ``"mutagen"`` arg is rewritten to the managed binary path so
    callers can write the natural ``["mutagen", ...]`` invocation.
    """
    resolved = args
    if args and args[0] == "mutagen":
        resolved = [_mutagen_bin(), *args[1:]]
    return subprocess.run(resolved, capture_output=capture_output, text=True, env=_mutagen_env())


def mutagen_installed() -> bool:
    """Return whether the mutagen CLI is available (managed or on PATH)."""
    return (_MANAGED_MUTAGEN_DIR / "mutagen").is_file() or shutil.which("mutagen") is not None


def get_installed_mutagen_version() -> str | None:
    """Return the installed mutagen CLI version, or ``None`` if undetermined.

    ``mutagen version`` prints ``X.Y.Z`` on a single line.
    """
    result = _run(["mutagen", "version"], capture_output=True)
    if result.returncode != 0:
        return None
    version = (result.stdout or "").strip()
    return version or None


def _install_mutagen(*, verbose: bool = False) -> None:
    """Install mutagen into ``~/.hogli/bin`` from the official GitHub release.

    Downloads the release tarball, verifies it against the pinned SHA256, then
    extracts both ``mutagen`` and ``mutagen-agents.tar.gz`` into the managed
    directory. Verification happens before extraction so a tampered or MITMed
    tarball never reaches disk as an executable. The agents archive is unpacked
    lazily by mutagen on first sync to ``~/.mutagen-agents/`` -- we just have to
    ship it next to the binary.
    """
    system, arch = _mutagen_platform()
    expected_sha = _MUTAGEN_SHA256.get((system, arch))
    if expected_sha is None:
        _fail(f"No pinned mutagen checksum for {system}/{arch}; refusing to install an unverified binary.")

    url = _mutagen_release_url()
    click.echo(f"Installing mutagen CLI v{_MUTAGEN_VERSION}...")

    _MANAGED_MUTAGEN_DIR.mkdir(parents=True, exist_ok=True)
    tarball = _MANAGED_MUTAGEN_DIR / f"mutagen_{system}_{arch}_v{_MUTAGEN_VERSION}.tar.gz"

    # Run curl and tar directly (no shell): the inputs aren't user-controlled,
    # but argv avoids any quoting/injection surface and needs no pipefail dance.
    download = ["curl", "-fsSL", "-o", str(tarball), url]
    result = subprocess.run(download, text=True, capture_output=not verbose)
    if result.returncode != 0:
        if not verbose:
            click.echo(result.stdout or "")
            click.echo(result.stderr or "", err=True)
        tarball.unlink(missing_ok=True)
        _fail(f"Mutagen download failed.\nTry manually: {' '.join(download)}")

    actual_sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        tarball.unlink(missing_ok=True)
        _fail(
            f"Mutagen tarball checksum mismatch for {system}/{arch}.\n"
            f"  expected {expected_sha}\n"
            f"  got      {actual_sha}\n"
            "Refusing to install a tampered or corrupt binary."
        )

    extract = ["tar", "-xz", "-C", str(_MANAGED_MUTAGEN_DIR), "-f", str(tarball), "mutagen", "mutagen-agents.tar.gz"]
    result = subprocess.run(extract, text=True, capture_output=not verbose)
    tarball.unlink(missing_ok=True)
    if result.returncode != 0:
        if not verbose:
            click.echo(result.stdout or "")
            click.echo(result.stderr or "", err=True)
        _fail(f"Mutagen extraction failed.\nTry manually: {' '.join(extract)}")

    managed = _MANAGED_MUTAGEN_DIR / "mutagen"
    if not managed.is_file():
        _fail(f"Mutagen install reported success but {managed} is missing.")


def ensure_mutagen_installed(*, verbose: bool = False) -> None:
    """Install mutagen at the pinned version, or reinstall on mismatch."""
    if not mutagen_installed():
        _install_mutagen(verbose=verbose)
        return

    installed = get_installed_mutagen_version()
    if installed is None:
        # Binary is present but `mutagen version` failed -- treat it as broken
        # (truncated download, incompatible libc) and reinstall rather than
        # silently shipping a CLI that crashes on the next sync command.
        click.echo("mutagen CLI is present but not runnable; reinstalling.")
        _install_mutagen(verbose=verbose)
    elif installed != _MUTAGEN_VERSION:
        click.echo(f"mutagen CLI v{installed} does not match expected v{_MUTAGEN_VERSION}.")
        _install_mutagen(verbose=verbose)
    else:
        click.echo("mutagen CLI is installed.")


def _resolve_real_ssh(name: str) -> str:
    """Absolute path to the real ssh/scp the shim should exec.

    Searches standard locations first (robust against a hijacked ``PATH``), then
    falls back to a ``PATH`` lookup with the shim dir removed so the shim can
    never resolve to itself.
    """
    for candidate in (f"/usr/bin/{name}", f"/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    entries = [e for e in os.environ.get("PATH", "").split(os.pathsep) if e and Path(e) != _SSH_SHIM_DIR]
    return shutil.which(name, path=os.pathsep.join(entries)) or name


def _write_owner_only(target: Path, content: str) -> None:
    """Atomically write ``content`` as an owner-only (0o700) executable.

    Writes to a fresh temp opened with a restrictive mode (umask only clears
    bits, and 0o700 has none in group/other, so it lands at 0o700) and renames
    it into place, so the script is never briefly world-readable or half-written.
    """
    tmp = target.with_name(f".{target.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o700)
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, target)


def ensure_ssh_shim() -> Path:
    """Write the ssh/scp keepalive-rewriting shims, returning their directory.

    Idempotent: each shim is rewritten only when its content (which embeds the
    resolved real-binary path and keepalive count) changes. mutagen invokes both
    ssh and scp, so both are shimmed; the rewrite is a no-op for any arg that
    isn't ``-oServerAliveCountMax=``.
    """
    _SSH_SHIM_DIR.mkdir(parents=True, exist_ok=True)
    # The daemon execs these scripts, so keep the dir and scripts owner-only: no
    # other local account can tamper with what runs as us, and they need no wider
    # access. The dir chmod also self-heals an older world-readable install.
    _SSH_SHIM_DIR.chmod(0o700)
    for name in ("ssh", "scp"):
        target = _SSH_SHIM_DIR / name
        content = _SHIM_TEMPLATE.format(count=_KEEPALIVE_COUNT, real=_resolve_real_ssh(name))
        if not target.exists() or target.read_text() != content:
            _write_owner_only(target, content)
        else:
            target.chmod(0o700)  # content already current; just heal perms
    return _SSH_SHIM_DIR


def _daemon_pids() -> list[int]:
    """PIDs of running mutagen daemon processes (best-effort, cross-platform)."""
    try:
        # POSIX `-A -o` (not BSD `-axo`) so this parses on both macOS and Linux.
        result = subprocess.run(["ps", "-A", "-o", "pid=,args="], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for line in result.stdout.splitlines():
        pid_str, _, args = line.strip().partition(" ")
        # `daemon run` is the daemon's own subcommand -- specific enough to skip
        # transient `ps`/`grep` lines that merely mention "mutagen daemon".
        if "mutagen" in args and "daemon run" in args and pid_str.isdigit():
            pids.append(int(pid_str))
    return pids


def _daemon_ssh_path(pid: int) -> str | None:
    """The ``MUTAGEN_SSH_PATH`` a process was started with, or ``None`` (best-effort).

    The value can legitimately contain spaces (a home dir like ``/Users/John
    Doe``), so both branches preserve them: Linux reads ``/proc/<pid>/environ``,
    which is NUL-delimited; macOS/BSD parse ``ps eww``, whose env is
    space-delimited with no per-entry boundary, so we capture from our key up to
    the next ``KEY=`` (or line end) rather than splitting on whitespace.
    """
    if platform.system() == "Linux":
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            return None
        for entry in raw.split(b"\0"):
            key, sep, value = entry.partition(b"=")
            if sep and key == b"MUTAGEN_SSH_PATH":
                return value.decode(errors="replace")
        return None
    try:
        result = subprocess.run(["ps", "eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(?:^|\s)MUTAGEN_SSH_PATH=(.*?)(?=\s\S+=|$)", result.stdout)
    return match.group(1) if match else None


def _daemon_uses_shim(shim_dir: Path) -> bool:
    """Whether a running daemon already routes ssh through our shim."""
    target = str(shim_dir)
    return any(_daemon_ssh_path(pid) == target for pid in _daemon_pids())


def ensure_daemon_with_shim() -> None:
    """Ensure the mutagen daemon spawns ssh through the keepalive shim.

    The daemon -- not the create call -- spawns ssh, so the shim only takes
    effect if the daemon's own env carries ``MUTAGEN_SSH_PATH``. A
    launchd/systemd-*registered* daemon has its env owned by the service manager
    (the invoking shell's env never reaches it), so we deliberately do not
    register; instead we let mutagen auto-start the daemon as a child of a hogli
    subprocess, which inherits ``_mutagen_env``. If a stale or service-managed
    daemon is already running without the shim, reset it: stop (sessions are
    persisted and resume on the next start), unregister any autostart hook so the
    restart forks a child, then start a fresh daemon carrying the env.

    The trade-off versus the old ``mutagen daemon register`` is losing
    autostart-on-reboot; mutagen still starts the daemon on demand on the next
    sync command, so an existing session simply resumes when the user next runs
    ``hogli devbox:sync``.
    """
    shim_dir = ensure_ssh_shim()
    if _daemon_uses_shim(shim_dir):
        return
    _run(["mutagen", "daemon", "stop"], capture_output=True)
    _run(["mutagen", "daemon", "unregister"], capture_output=True)
    result = _run(["mutagen", "daemon", "start"], capture_output=True)
    if result.returncode != 0:
        click.echo(
            click.style(
                "Warning: could not start the mutagen daemon with the keepalive shim; "
                "sync may not survive network blips. A sync command will retry the start.",
                fg="yellow",
            )
        )
        stderr = (result.stderr or "").strip()
        if stderr:
            click.echo(f"  {stderr}", err=True)


# ---------------------------------------------------------------------------
# User config
# ---------------------------------------------------------------------------

_USER_CONFIG_PATH = Path.home() / ".hogli" / "mutagen.yml"
_PACKAGED_DEFAULTS = Path(__file__).parent / "mutagen_defaults.yml"


def user_mutagen_config_path() -> Path:
    """Return the path where the user-editable mutagen defaults live."""
    return _USER_CONFIG_PATH


def _config_seed_path(config_path: Path) -> Path:
    """Sidecar recording the hash of the defaults we last seeded into ``config_path``."""
    return config_path.with_name(f".{config_path.name}.seed")


def ensure_user_mutagen_config() -> Path:
    """Seed (and refresh) ``~/.hogli/mutagen.yml`` from the packaged defaults.

    The user file is intentionally editable, so edits are never clobbered. But an
    *untouched* copy is refreshed when the packaged defaults change: we record the
    hash of what we seeded in a sidecar and overwrite only while the on-disk file
    still matches that recorded seed. Without this, a shipped fix to the ignore
    list (e.g. a newly-ignored build dir) would stay dead forever for anyone who
    seeded an older copy. A file whose contents differ from the recorded seed is
    treated as user-owned and left alone (so pre-sidecar files are preserved --
    delete them to re-seed).
    """
    target = user_mutagen_config_path()
    packaged = _PACKAGED_DEFAULTS.read_text()
    packaged_hash = hashlib.sha256(packaged.encode()).hexdigest()
    seed_path = _config_seed_path(target)

    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(packaged)
        seed_path.write_text(packaged_hash)
        return target

    current_hash = hashlib.sha256(target.read_text().encode()).hexdigest()
    if current_hash == packaged_hash:
        seed_path.write_text(packaged_hash)  # keep the sidecar in step for the next bump
        return target

    seeded_hash = seed_path.read_text().strip() if seed_path.exists() else None
    if seeded_hash == current_hash:
        # Untouched since we seeded it, but the packaged defaults changed -- refresh.
        target.write_text(packaged)
        seed_path.write_text(packaged_hash)
    return target


# Single source of truth for the label hogli stamps on every sync session, so the
# create side (sync_create) and the lookup side (selector) can never drift apart.
_WORKSPACE_LABEL_KEY = "hogli-workspace"


def workspace_labels(workspace: str) -> dict[str, str]:
    """Return the labels hogli attaches when creating a sync session for ``workspace``."""
    return {_WORKSPACE_LABEL_KEY: workspace}


def workspace_label_selector(workspace: str) -> str:
    """Return the mutagen ``--label-selector`` string for a hogli workspace."""
    return f"{_WORKSPACE_LABEL_KEY}={workspace}"


def conflict_count(session: dict[str, Any]) -> int:
    """Return a session's true conflict count.

    ``mutagen sync list`` caps the inline ``conflicts`` array (10 by default)
    and reports the remainder as ``excludedConflicts`` -- summing both is the
    only way to get the real total. Reading just ``len(conflicts)`` silently
    undercounts and pins the display at 10 for any heavily-diverged sync.
    """
    shown = session.get("conflicts") or []
    excluded = session.get("excludedConflicts") or 0
    try:
        return len(shown) + int(excluded)
    except (TypeError, ValueError):
        return len(shown)


# ---------------------------------------------------------------------------
# Sync session wrappers
# ---------------------------------------------------------------------------

# `mutagen sync list` exits 1 with "no sessions" when a label selector matches
# nothing. We treat that as "empty list", not as an error.
_NO_SESSIONS_MARKERS = ("no sessions", "no synchronization sessions")


def sync_create(
    *,
    name: str,
    src: str,
    dst: str,
    config_path: Path | None,
    labels: dict[str, str],
) -> None:
    """Create a one-way-safe sync session from ``src`` to ``dst``.

    ``one-way-safe`` propagates local->remote, preserves remote-only files
    (so the AMI's prewarmed ``node_modules`` / ``target`` / ``.venv`` survive
    even outside the ignore list), and surfaces conflicts when remote files
    diverge from local.
    """
    args: list[str] = [
        "mutagen",
        "sync",
        "create",
        "--name",
        name,
        "--mode",
        "one-way-safe",
        "--ignore-vcs",
    ]
    if config_path is not None:
        args += ["--configuration-file", str(config_path)]
    for key, value in labels.items():
        args += ["--label", f"{key}={value}"]
    args += [src, dst]

    result = _run(args)
    if result.returncode != 0:
        _fail(f"Failed to create mutagen sync session '{name}'.")


def sync_list(*, label_selector: str | None = None) -> list[dict[str, Any]]:
    """Return sync sessions as parsed JSON dicts.

    Uses mutagen's ``--template '{{ json . }}'`` to render sessions through
    its public model types. Returns ``[]`` when no matching session exists,
    when mutagen isn't installed yet, or when the daemon is offline -- the
    callers treat all three cases as "no active sync", which is correct.
    """
    if not mutagen_installed():
        return []

    args: list[str] = ["mutagen", "sync", "list", "--template", "{{ json . }}"]
    if label_selector:
        args += ["--label-selector", label_selector]

    try:
        result = _run(args, capture_output=True)
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    stdout = (result.stdout or "").strip()
    if not stdout:
        return []
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [s for s in parsed if isinstance(s, dict)]


def _label_op(verb: str, label_selector: str) -> None:
    """Run a label-scoped sync lifecycle command (terminate/pause/resume/flush).

    No-ops when nothing matches the selector. ``sync_list`` is resilient to a
    missing binary or an offline daemon, so this both keeps "no session" a
    silent success and prevents a raw ``FileNotFoundError`` crash on a machine
    that never installed mutagen (the lifecycle flags skip the install step).
    """
    if not label_selector:
        _fail(f"Refusing to {verb} sync sessions without a label selector.")
    if not sync_list(label_selector=label_selector):
        return
    args = ["mutagen", "sync", verb, "--label-selector", label_selector]
    result = _run(args, capture_output=True)
    if result.returncode != 0:
        combined = (result.stdout or "") + (result.stderr or "")
        # The session may have vanished between the list and the op (a race).
        if any(marker in combined.lower() for marker in _NO_SESSIONS_MARKERS):
            return
        click.echo((result.stderr or result.stdout or "").strip(), err=True)
        _fail(f"`mutagen sync {verb}` failed for selector {label_selector!r}.")


def sync_terminate(label_selector: str) -> None:
    """Terminate sync sessions matching the label selector. No-op if none exist."""
    _label_op("terminate", label_selector)


def sync_pause(label_selector: str) -> None:
    """Pause sync sessions matching the label selector. No-op if none exist."""
    _label_op("pause", label_selector)


def sync_resume(label_selector: str) -> None:
    """Resume sync sessions matching the label selector. No-op if none exist."""
    _label_op("resume", label_selector)


def sync_flush(label_selector: str) -> None:
    """Flush sync sessions matching the label selector. No-op if none exist."""
    _label_op("flush", label_selector)
