"""`hogli devbox:sync` -- one-way-safe local->remote file sync for Coder devboxes.

Lets engineers edit code locally while running the full PostHog dev stack
on a Coder devbox. Local is the source of truth; nothing flows back to local
automatically. Sessions are addressed by mutagen label, not name, so multiple
workspaces stay independently controllable.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import click

from . import mutagen
from .cli import _workspace_arg_suffix, resolve_workspace_name, workspace_argument
from .coder import _fail, ensure_runtime_ready, get_workspace, get_workspace_status

_REMOTE_REPO_PATH = "/home/coder/posthog"


def _detect_local_posthog_checkout() -> Path:
    """Find the local PostHog checkout root by walking up from cwd.

    A checkout is identified by a co-located ``hogli.yaml`` and ``.git``
    directory at the same level. Bails with a hint if we can't find one --
    running ``hogli devbox:sync`` from anywhere outside the repo is almost
    certainly a mistake.
    """
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "hogli.yaml").is_file() and (candidate / ".git").exists():
            return candidate
    _fail(
        "Could not find a PostHog checkout above the current directory.\n"
        "Run `hogli devbox:sync` from inside a `posthog` clone."
    )
    raise SystemExit(1)  # unreachable; helps the type checker see no fall-through


def _ensure_ssh_config_for_workspace(workspace: str) -> None:
    """Ensure ``ssh coder.{workspace}`` resolves before mutagen tries to dial it.

    We check via ``ssh -G`` (which never connects, just resolves config). If
    the host has no specific entry, mutagen would fail with an opaque SSH
    error; we'd rather tell the user to rerun setup.
    """
    host = f"coder.{workspace}"
    result = subprocess.run(["ssh", "-G", host], capture_output=True, text=True)
    if result.returncode != 0:
        _fail(
            f"SSH config for `{host}` is missing. Run `hogli devbox:setup` to install "
            "Coder workspace entries into your ~/.ssh/config."
        )


def _format_session_status(session: dict[str, Any]) -> str:
    """Render a single mutagen session as a few short lines."""
    name = session.get("name") or session.get("identifier", "?")
    paused = session.get("paused", False)
    status = session.get("status", "")
    alpha = session.get("alpha", {})
    beta = session.get("beta", {})
    alpha_path = alpha.get("path", "?") if isinstance(alpha, dict) else "?"
    beta_path = beta.get("path", "?") if isinstance(beta, dict) else "?"
    state = "paused" if paused else (status or "running")
    lines = [
        f"  {name}",
        f"    state: {state}",
        f"    alpha: {alpha_path}",
        f"    beta:  {beta_path}",
    ]
    # Conflicts are the whole point of one-way-safe: a remote file diverged and
    # mutagen refused to overwrite it. Surface them or the sync looks healthy
    # while the user's edits silently never land. Conflicts are per-path: only
    # the diverged paths are blocked, everything else keeps syncing.
    conflicts = mutagen.conflict_count(session)
    if conflicts:
        lines.append(
            f"    conflicts: {conflicts} (these paths diverged on the remote and won't sync until resolved; other files are unaffected)"
        )
    last_error = session.get("lastError")
    if last_error:
        lines.append(f"    error: {last_error}")
    return "\n".join(lines)


def _print_sessions(sessions: list[dict[str, Any]]) -> None:
    """Print the sync sessions returned by mutagen, one per block."""
    if not sessions:
        click.echo("No active sync sessions.")
        return
    for session in sessions:
        click.echo(_format_session_status(session))


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw mutagen session to a stable shape for programmatic callers.

    Agents driving the sync loop need to answer "am I synced, and is anything
    conflicting?" without scraping human text. ``conflictPaths`` lists only the
    roots mutagen inlines (capped at 10); ``conflicts`` is the true total, so a
    caller compares ``len(conflictPaths)`` to ``conflicts`` to know it's seeing
    a truncated sample.
    """
    paused = bool(session.get("paused", False))
    status = str(session.get("status", "") or "").strip()
    shown = session.get("conflicts") or []
    alpha = session.get("alpha") if isinstance(session.get("alpha"), dict) else {}
    beta = session.get("beta") if isinstance(session.get("beta"), dict) else {}
    return {
        "name": session.get("name") or session.get("identifier"),
        "state": "paused" if paused else (status or "running"),
        "paused": paused,
        "conflicts": mutagen.conflict_count(session),
        "conflictPaths": [c.get("root") for c in shown if isinstance(c, dict) and c.get("root")],
        "lastError": session.get("lastError"),
        "alpha": alpha.get("path"),
        "beta": beta.get("path"),
    }


@click.command(name="devbox:sync", help="Mirror your local PostHog checkout to a devbox")
@workspace_argument
@click.option("--status", "show_status", is_flag=True, help="Show the current sync state")
@click.option(
    "--json", "as_json", is_flag=True, help="Print sync state as JSON (implies --status; for scripts and agents)"
)
@click.option("--pause", is_flag=True, help="Pause the sync session")
@click.option("--resume", is_flag=True, help="Resume a paused sync session")
@click.option("--terminate", is_flag=True, help="Tear down the sync session")
@click.option("--flush", is_flag=True, help="Force a flush of pending changes")
@click.option("-v", "--verbose", is_flag=True, help="Show full install output")
def cmd_sync(
    workspace: str | None,
    show_status: bool,
    as_json: bool,
    pause: bool,
    resume: bool,
    terminate: bool,
    flush: bool,
    verbose: bool,
) -> None:
    """Create or manage a one-way-safe mutagen sync session for a devbox.

    Default action is an idempotent create: re-running on a workspace that
    already has a session just prints the status. Use the flag variants to
    operate on an existing session by label.
    """
    chosen = sum([show_status, pause, resume, terminate, flush])
    if chosen > 1:
        raise click.UsageError("Pick at most one of --status, --pause, --resume, --terminate, --flush.")
    if as_json and (pause or resume or terminate or flush):
        raise click.UsageError("--json reports state only; it can't combine with --pause/--resume/--terminate/--flush.")
    if workspace and workspace.startswith("@"):
        # Local is the source of truth: syncing onto another user's box would
        # push your checkout over theirs. v1 targets your own devboxes only.
        _fail("devbox:sync only targets your own devboxes; `@user` shared targets are not supported.")

    name, workspaces = resolve_workspace_name(workspace)
    label = mutagen.workspace_label_selector(name)

    # Lifecycle subcommands don't need the full runtime preflight -- they
    # just talk to the local mutagen daemon. Keep them fast and offline-safe.
    if as_json:
        sessions = mutagen.sync_list(label_selector=label)
        click.echo(json.dumps([_session_summary(s) for s in sessions]))
        return
    if show_status:
        _print_sessions(mutagen.sync_list(label_selector=label))
        return
    if pause:
        mutagen.sync_pause(label)
        click.echo(f"Paused sync for {name}.")
        return
    if resume:
        mutagen.sync_resume(label)
        click.echo(f"Resumed sync for {name}.")
        return
    if terminate:
        mutagen.sync_terminate(label)
        click.echo(f"Terminated sync for {name}.")
        return
    if flush:
        mutagen.sync_flush(label)
        click.echo(f"Flushed sync for {name}.")
        return

    # Default path: idempotent create. Install mutagen and bring the daemon up
    # first so the existing-session check sees sessions persisted across daemon
    # restarts; a re-run then short-circuits before the heavier coder/SSH
    # preflight below. (ensure_runtime_ready covers the coder install check.)
    mutagen.ensure_mutagen_installed(verbose=verbose)
    mutagen.ensure_daemon_with_shim()
    if mutagen.sync_list(label_selector=label):
        click.echo(
            f"Sync already running for {name}. Use `hogli devbox:sync{_workspace_arg_suffix(name)} --status` to inspect."
        )
        return

    ensure_runtime_ready()
    _ensure_workspace_running(name, workspaces)
    _ensure_ssh_config_for_workspace(name)
    config_path = mutagen.ensure_user_mutagen_config()

    local_path = _detect_local_posthog_checkout()
    click.echo(f"Creating sync: {local_path} -> coder.{name}:{_REMOTE_REPO_PATH}")
    mutagen.sync_create(
        name=f"ph-{name}",
        src=str(local_path),
        dst=f"coder.{name}:{_REMOTE_REPO_PATH}",
        config_path=config_path,
        labels=mutagen.workspace_labels(name),
    )
    click.echo("Sync created. Initial scan and copy may take a few minutes for large checkouts.")
    click.echo(f"Inspect: hogli devbox:sync{_workspace_arg_suffix(name)} --status")


def _ensure_workspace_running(name: str, workspaces: list[dict[str, Any]] | None) -> None:
    """Fail early with a clear message if the target devbox isn't running.

    mutagen dials the box over SSH; a stopped box otherwise surfaces as an
    opaque connection error partway through the sync. Best-effort: when the
    workspace list is unavailable (e.g. a shared ``@user`` target) we skip the
    check rather than block on an unknowable state.
    """
    if not workspaces:
        return
    workspace = get_workspace(name, workspaces)
    if workspace is None:
        return
    status = get_workspace_status(workspace)
    if status != "running":
        _fail(f"Devbox '{name}' is {status}, not running. Run `hogli devbox:start` first.")
