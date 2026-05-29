"""Mutagen CLI wrapper for one-way local->remote file sync.

Mirrors ``coder.py`` shape: a managed binary lives in ``~/.hogli/bin/``,
version is pinned, and all subprocess interactions are isolated behind thin
wrappers. v1 only targets Coder workspaces as the remote endpoint.
"""

from __future__ import annotations

import json
import shlex
import shutil
import platform
import subprocess
from pathlib import Path
from typing import Any

import click

from .coder import _fail

_MANAGED_MUTAGEN_DIR = Path.home() / ".hogli" / "bin"
_MUTAGEN_VERSION = "0.18.1"
_RELEASE_URL_TEMPLATE = (
    "https://github.com/mutagen-io/mutagen/releases/download/v{version}/mutagen_{os}_{arch}_v{version}.tar.gz"
)


def _mutagen_release_url(version: str = _MUTAGEN_VERSION) -> str:
    """Build the GitHub release tarball URL for the current platform.

    Mutagen's release naming is ``mutagen_{os}_{arch}_v{version}.tar.gz``
    where ``os`` is ``darwin``/``linux`` and ``arch`` is ``amd64``/``arm64``.
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

    return _RELEASE_URL_TEMPLATE.format(version=version, os=system, arch=arch)


def _mutagen_bin() -> str:
    """Return the path to the hogli-managed mutagen binary, falling back to PATH."""
    managed = _MANAGED_MUTAGEN_DIR / "mutagen"
    if managed.is_file():
        return str(managed)
    return shutil.which("mutagen") or "mutagen"


def _run(args: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a mutagen subprocess with consistent text handling.

    A leading ``"mutagen"`` arg is rewritten to the managed binary path so
    callers can write the natural ``["mutagen", ...]`` invocation.
    """
    resolved = args
    if args and args[0] == "mutagen":
        resolved = [_mutagen_bin(), *args[1:]]
    return subprocess.run(resolved, capture_output=capture_output, text=True)


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

    Extracts both ``mutagen`` and ``mutagen-agents.tar.gz`` from the tarball
    into the managed directory. The agents archive is unpacked lazily by
    mutagen on first sync to ``~/.mutagen-agents/`` -- we just have to ship
    it next to the binary.
    """
    url = _mutagen_release_url()
    click.echo(f"Installing mutagen CLI v{_MUTAGEN_VERSION}...")

    _MANAGED_MUTAGEN_DIR.mkdir(parents=True, exist_ok=True)
    # `set -o pipefail` so a curl failure fails the pipeline; otherwise `tar`
    # extracts an empty stream and we silently "install" nothing. Invoke via
    # `bash` because `/bin/sh` is `dash` on Debian/Ubuntu and rejects `-o pipefail`.
    cmd = (
        f"set -o pipefail; curl -fsSL {shlex.quote(url)} | "
        f"tar -xz -C {shlex.quote(str(_MANAGED_MUTAGEN_DIR))} mutagen mutagen-agents.tar.gz"
    )
    result = subprocess.run(["bash", "-c", cmd], text=True, capture_output=not verbose)
    if result.returncode != 0:
        if not verbose:
            click.echo(result.stdout or "")
            click.echo(result.stderr or "", err=True)
        _fail(f"Mutagen CLI installation failed.\nTry manually: {cmd}")

    managed = _MANAGED_MUTAGEN_DIR / "mutagen"
    if not managed.is_file():
        _fail(f"Mutagen install reported success but {managed} is missing.\nTry manually: {cmd}")


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


def register_daemon() -> None:
    """Install the mutagen daemon's autostart hook (LaunchAgent / systemd user unit).

    Idempotent on mutagen's side -- re-running just re-applies the same hook.
    Best-effort: any failure is logged as a warning, not fatal, because the
    daemon will still start on demand the first time a sync command runs;
    autostart just means it survives reboots without intervention.
    """
    result = _run(["mutagen", "daemon", "register"], capture_output=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        click.echo(
            click.style(
                "Warning: `mutagen daemon register` failed; sync will still work "
                "but the daemon won't auto-restart after reboot.",
                fg="yellow",
            )
        )
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


def ensure_user_mutagen_config() -> Path:
    """Copy the packaged ``mutagen_defaults.yml`` to ``~/.hogli/mutagen.yml`` if absent.

    The user-side file is intentionally user-editable: a developer can tweak
    ignore paths or sync mode without forking hogli. We never overwrite an
    existing file -- bumps to the packaged defaults are opt-in via ``rm`` +
    ``hogli devbox:setup``.
    """
    target = user_mutagen_config_path()
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_PACKAGED_DEFAULTS.read_text())
    return target


def workspace_label_selector(workspace: str) -> str:
    """Return the mutagen ``--label-selector`` string for a hogli workspace."""
    return f"hogli-workspace={workspace}"


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
