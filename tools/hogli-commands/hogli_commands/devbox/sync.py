"""`hogli devbox:sync` -- one-way-safe local->remote file sync for Coder devboxes.

Lets engineers edit code locally while running the full PostHog dev stack
on a Coder devbox. Local is the source of truth; nothing flows back to local
automatically. Sessions are addressed by mutagen label, not name, so multiple
workspaces stay independently controllable.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import click

from . import mutagen
from .cli import resolve_workspace_name, workspace_argument
from .coder import _fail, ensure_coder_installed, ensure_runtime_ready, extract_workspace_label

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
    return "\n".join(
        [
            f"  {name}",
            f"    state: {state}",
            f"    alpha: {alpha_path}",
            f"    beta:  {beta_path}",
        ]
    )


def _print_sessions(sessions: list[dict[str, Any]]) -> None:
    """Print the sync sessions returned by mutagen, one per block."""
    if not sessions:
        click.echo("No active sync sessions.")
        return
    for session in sessions:
        click.echo(_format_session_status(session))


@click.command(name="devbox:sync", help="Mirror your local PostHog checkout to a devbox")
@workspace_argument
@click.option("--status", "show_status", is_flag=True, help="Show the current sync state")
@click.option("--pause", is_flag=True, help="Pause the sync session")
@click.option("--resume", is_flag=True, help="Resume a paused sync session")
@click.option("--terminate", is_flag=True, help="Tear down the sync session")
@click.option("--flush", is_flag=True, help="Force a flush of pending changes")
@click.option("-v", "--verbose", is_flag=True, help="Show full install output")
def cmd_sync(
    workspace: str | None,
    show_status: bool,
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

    name, _ = resolve_workspace_name(workspace)
    label = mutagen.workspace_label_selector(name)

    # Lifecycle subcommands don't need the full runtime preflight -- they
    # just talk to the local mutagen daemon. Keep them fast and offline-safe.
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

    # Default path: idempotent create.
    ensure_runtime_ready()
    ensure_coder_installed(verbose=verbose)
    mutagen.ensure_mutagen_installed(verbose=verbose)
    mutagen.register_daemon()
    _ensure_ssh_config_for_workspace(name)
    config_path = mutagen.ensure_user_mutagen_config()

    existing = mutagen.sync_list(label_selector=label)
    if existing:
        click.echo(
            f"Sync already running for {name}. Use `hogli devbox:sync {_label_suffix(name)}--status` to inspect."
        )
        return

    local_path = _detect_local_posthog_checkout()
    click.echo(f"Creating sync: {local_path} -> coder.{name}:{_REMOTE_REPO_PATH}")
    mutagen.sync_create(
        name=f"ph-{name}",
        src=str(local_path),
        dst=f"coder.{name}:{_REMOTE_REPO_PATH}",
        config_path=config_path,
        labels={"hogli-workspace": name},
    )
    click.echo("Sync created. Initial scan and copy may take a few minutes for large checkouts.")
    click.echo(f"Inspect: hogli devbox:sync {_label_suffix(name)}--status")


def _label_suffix(workspace_name: str) -> str:
    """Render the workspace label suffix used by ``workspace_argument``-style CLIs."""
    label = extract_workspace_label(workspace_name)
    return f"{label} " if label else ""
