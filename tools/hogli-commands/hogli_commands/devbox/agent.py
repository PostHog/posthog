from __future__ import annotations

import time
import shlex
import base64
import subprocess
from pathlib import Path
from typing import Any

import click

from .cli import _workspace_arg_suffix, start_or_create_workspace
from .coder import (
    REGIONS,
    _fail,
    coder_ssh_alias_configured,
    ensure_runtime_ready,
    get_coder_url,
    get_preview_app,
    get_workspace,
    get_workspace_status,
    has_claude_oauth_secret,
    list_user_workspaces,
    run_remote_script,
    server_supports_user_secrets,
)
from .sync import (
    create_sync_session,
    find_local_posthog_checkout,
    flush_sync_sessions,
    list_sync_sessions,
    sync_session_exists,
    terminate_sync_sessions,
)

_REMOTE_AGENT_DIR = "$HOME/.hogli/agent"
_LAUNCH_TIMEOUT_SECONDS = 60
_DOCTOR_HINT = "Run `hogli devbox:doctor` to check your devbox access, then retry."
AGENT_INSTRUCTIONS = (
    "You are running on a PostHog devbox in ~/posthog. Nothing you change here syncs back to the user's machine. "
    "Before you edit any file, create a new git branch. When you finish, commit your work, push the branch, "
    "and say which branch you pushed."
)


def _session_name() -> str:
    return time.strftime("hogli-agent-%Y%m%d-%H%M%S")


def _launch_script(session: str, prompt: str, permission_mode: str | None) -> str:
    claude_args = ["--permission-mode", permission_mode] if permission_mode else []
    runner = "\n".join(
        [
            "#!/usr/bin/env bash",
            'cd "$HOME/posthog"',
            f'exec claude {shlex.join(claude_args)} "$@" "$(cat "$(dirname "$0")/{session}.prompt")"',
        ]
    )
    prompt_b64 = base64.b64encode(prompt.encode()).decode()
    runner_b64 = base64.b64encode(runner.encode()).decode()
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "if ! bash -lc 'command -v claude' >/dev/null 2>&1; then echo claude-missing; exit 3; fi",
            f'dir="{_REMOTE_AGENT_DIR}"',
            'mkdir -p "$dir"',
            f'echo {prompt_b64} | base64 -d > "$dir/{session}.prompt"',
            f'echo {runner_b64} | base64 -d > "$dir/{session}.sh"',
            "if command -v tmux >/dev/null 2>&1; then",
            f'  tmux new-session -d -s {session} -c "$HOME/posthog" "bash -l $dir/{session}.sh; exec bash -l"',
            "  echo mode=tmux",
            "else",
            f'  nohup bash -l "$dir/{session}.sh" -p > "$dir/{session}.log" 2>&1 < /dev/null &',
            f'  echo $! > "$dir/{session}.pid"',
            "  echo mode=nohup",
            "fi",
        ]
    )


def _exec_suffix(name: str) -> str:
    label = _workspace_arg_suffix(name).strip()
    return f" -n {label}" if label else ""


def _print_plan(
    workspace: str | None, region: str | None, checkout: Path | None, no_sync: bool, live_sync: bool, prompt: str
) -> None:
    target = f"devbox '{workspace}'" if workspace else "your default devbox"
    if region and not workspace:
        target = f"your default devbox in {region}"
    if no_sync:
        sync_step = "Skip the mirror (--no-sync), and stop a mirror that is already running."
    elif checkout is None:
        sync_step = "Skip the mirror: the current directory is not in a PostHog checkout."
        if not live_sync:
            sync_step += " Stop a mirror that is already running."
    else:
        sync_step = f"Mirror {checkout} to ~/posthog on the box, reusing an existing mirror, and report conflicts."
        if live_sync:
            sync_step += " Keep the mirror running (--live-sync)."
        else:
            sync_step += " Then stop the mirror, so the box is the source of truth."
    steps = [
        f"Check that {get_coder_url()} is reachable.",
        f"Start or resume {target}, creating it if it does not exist.",
        sync_step,
        "Launch Claude Code in ~/posthog on the box in a tmux session, or with nohup if tmux is missing. "
        "The prompt tells it to work on a new branch and to commit and push its work.",
        "Print how to attach to and stop the agent, and the app URL if the box has one.",
    ]
    click.echo("Dry run. hogli devbox:agent would:")
    for index, step in enumerate(steps, start=1):
        click.echo(f"  {index}. {step}")
    click.echo(f"Prompt: {prompt}")


def _ensure_reachable() -> None:
    try:
        ensure_runtime_ready()
    except SystemExit:
        click.echo(_DOCTOR_HINT)
        raise


def _mirror_checkout(
    name: str, workspaces: list[dict[str, Any]], checkout: Path, *, live_sync: bool, verbose: bool
) -> None:
    suffix = _workspace_arg_suffix(name)
    if sync_session_exists(name, verbose=verbose):
        other_sources = sorted({str(s["alpha"]) for s in list_sync_sessions(name) if s["alpha"] != str(checkout)})
        if other_sources:
            _fail(
                f"'{name}' already mirrors {other_sources[0]}, not {checkout}. "
                f"Run `hogli devbox:agent` from that checkout, pass --no-sync, "
                f"or stop that mirror with `hogli devbox:sync{suffix} --terminate`."
            )
        click.echo(f"Reusing the sync for {name}.")
    else:
        create_sync_session(name, workspaces, checkout)
    click.echo("Waiting for the first sync to finish...")
    sessions = flush_sync_sessions(name)
    conflicts = sum(session["conflicts"] for session in sessions)
    if conflicts:
        paths = "".join(f"\n    {path}" for session in sessions for path in session["conflictPaths"])
        click.echo(
            click.style(
                f"⚠ {conflicts} path{'s' if conflicts != 1 else ''} conflict on the box, so the box kept its own copy. "
                "A new box is on master, so files your branch changed show up here. Other files synced."
                + (f" Inspect: hogli devbox:sync{suffix} --status" if live_sync else paths),
                fg="yellow",
            )
        )
    if live_sync:
        click.echo("The sync keeps running and only copies local changes to the box. Edits the agent makes stay there.")
        return
    _stop_mirror(name)


def _stop_mirror(name: str) -> None:
    terminate_sync_sessions(name)
    click.echo(
        f"Stopped the sync, so the box is now the source of truth for the agent. "
        f"Run `hogli devbox:sync{_workspace_arg_suffix(name)}` to start it again."
    )


def _warn_if_no_claude_token() -> None:
    if server_supports_user_secrets() and not has_claude_oauth_secret():
        click.echo(
            click.style(
                "No Claude Code token is stored for your devboxes, so Claude Code asks you to log in when you attach. "
                "Run `hogli devbox:setup --configure-claude` to store one, then `hogli devbox:restart`.",
                fg="yellow",
            )
        )


def _launch_agent(name: str, session: str, prompt: str, permission_mode: str | None) -> str:
    if not coder_ssh_alias_configured(name):
        _fail("SSH access for devboxes isn't configured. Run `hogli devbox:setup`, then retry.")
    try:
        result = run_remote_script(
            name, _launch_script(session, prompt, permission_mode), timeout=_LAUNCH_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        _fail(f"Timed out after {_LAUNCH_TIMEOUT_SECONDS}s starting Claude Code on '{name}'.")
    if "claude-missing" in result.stdout:
        _fail(f"Claude Code isn't installed on '{name}'. Run `hogli devbox:update` to get the latest template.")
    if result.returncode != 0:
        click.echo(result.stderr.strip(), err=True)
        _fail(f"Failed to start Claude Code on '{name}'.")
    return "nohup" if "mode=nohup" in result.stdout else "tmux"


def _print_agent_hints(name: str, session: str, mode: str) -> None:
    exec_cmd = f"hogli devbox:exec{_exec_suffix(name)} --"
    click.echo()
    if mode == "tmux":
        click.echo(f"  Attach   ssh -t coder.{name} tmux attach -t {session}")
        click.echo("           Detach again with Ctrl-b d.")
        click.echo(f"  Stop     {exec_cmd} tmux kill-session -t {session}")
    else:
        log = f"~/.hogli/agent/{session}.log"
        click.echo(f"  Log      {exec_cmd} bash -lc 'tail -f {log}'")
        click.echo(f"  Stop     {exec_cmd} bash -lc 'kill $(cat ~/.hogli/agent/{session}.pid)'")


def _print_preview_url(workspace: dict[str, Any]) -> None:
    preview = get_preview_app(workspace)
    if preview is None:
        return
    note = "" if preview.health == "healthy" else f" ({preview.health}. The app may not be running yet.)"
    click.echo(f"  App      {preview.url}{note}")


@click.command(
    name="devbox:agent",
    help="Start your devbox, mirror this checkout to it, and run Claude Code on it with PROMPT",
)
@click.argument("prompt")
@click.option("--name", "-n", "workspace_name", default=None, help="Workspace label")
@click.option(
    "--region",
    type=click.Choice(REGIONS),
    default=None,
    help="Region whose default devbox to use, creating it if needed. Same as `devbox:start --region`.",
)
@click.option("--no-sync", is_flag=True, help="Don't mirror the local checkout to the box")
@click.option(
    "--live-sync",
    is_flag=True,
    help="Keep the mirror running after the first sync instead of stopping it before the agent starts",
)
@click.option("--permission-mode", default=None, help="Passed to `claude --permission-mode`")
@click.option("--dry-run", is_flag=True, help="Print the steps without running them")
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
def devbox_agent(
    prompt: str,
    workspace_name: str | None,
    region: str | None,
    no_sync: bool,
    live_sync: bool,
    permission_mode: str | None,
    dry_run: bool,
    verbose: bool,
) -> None:
    if not prompt.strip():
        raise click.UsageError("PROMPT is empty.")
    if no_sync and live_sync:
        raise click.UsageError("Pass --no-sync or --live-sync, not both.")
    if workspace_name and workspace_name.startswith("@"):
        _fail("devbox:agent only targets your own devboxes; `@user` shared targets are not supported.")

    checkout = None if no_sync else find_local_posthog_checkout()
    if dry_run:
        _print_plan(workspace_name, region, checkout, no_sync, live_sync, prompt)
        return

    _ensure_reachable()
    name = start_or_create_workspace(workspace_name, region=region, verbose=verbose, show_connection_info=False)
    workspaces = list_user_workspaces()
    ws = get_workspace(name, workspaces)
    if ws is None or get_workspace_status(ws) != "running":
        status = get_workspace_status(ws) if ws is not None else "missing"
        _fail(f"Devbox '{name}' is {status}, not running. Retry `hogli devbox:agent` once it settles.")

    if checkout is not None:
        _mirror_checkout(name, workspaces, checkout, live_sync=live_sync, verbose=verbose)
    elif not live_sync and list_sync_sessions(name):
        _stop_mirror(name)

    _warn_if_no_claude_token()
    session = _session_name()
    mode = _launch_agent(name, session, f"{AGENT_INSTRUCTIONS}\n\n{prompt}", permission_mode)
    click.echo(f"Claude Code is running on '{name}' in ~/posthog ({mode} session {session}).")
    _print_agent_hints(name, session, mode)
    _print_preview_url(ws)
