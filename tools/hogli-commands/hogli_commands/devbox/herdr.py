"""Herdr support for devboxes: a devbox as a Herdr machine, and the plugin for herdr's worktrees.

Herdr's terminals run in herdr-core (`hc`), which reaches other machines over
ssh. Registering the devbox's ``coder.<name>`` alias as an `hc` machine lets
Herdr run terminals and agents on the box, and a space on that machine shows
them in the window.

The plugin in `tools/herdr-devbox-plugin` gives each worktree that herdr
creates on this machine its own devbox, through `devbox:worktree`.
"""

from __future__ import annotations

import json
import time
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click

from .coder import _fail, _ssh_host_alias

HERDR_URL = "https://herdr.dev"
_MACHINE_ADD_TIMEOUT = 300.0
_MACHINE_CONNECT_TIMEOUT = 60.0
_WINDOW_START_TIMEOUT = 20.0
_WINDOW_SEES_MACHINE_TIMEOUT = 15.0
_POLL_INTERVAL = 0.5
PLUGIN_ID = "posthog.devbox"
PLUGIN_DIR = Path("tools") / "herdr-devbox-plugin"


def _require_cli(name: str) -> None:
    if shutil.which(name) is None:
        _fail(
            f"`{name}` is not on PATH. Install Herdr from {HERDR_URL}, then retry.",
            cause="herdr_not_installed",
        )


def _run(args: list[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    # Output is captured, so a prompt would wait on input nobody can see.
    # Closing stdin makes it fail with an error instead.
    try:
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Report a timeout as a failed run, so that polling loops retry it and
        # other callers show their own error message instead of a traceback.
        return subprocess.CompletedProcess(args, 124, "", f"`{' '.join(args[:3])}` timed out after {timeout:.0f}s.")
    except OSError as error:
        # `hc` can be on PATH and still fail to start, such as a script whose interpreter is gone.
        return subprocess.CompletedProcess(args, 126, "", f"`{args[0]}` couldn't start: {error}")


def _run_json(args: list[str], *, failure: str, cause: str) -> dict[str, Any]:
    result = _run(args)
    if result.returncode != 0:
        _fail(f"{failure}\n{_output_of(result)}", cause=cause)
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    _fail(f"{failure}\n`{' '.join(args)}` printed something hogli can't read.", cause=cause)
    raise SystemExit(1)  # unreachable; helps ty see the function doesn't fall through


def _output_of(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def _ssh_targets(workspace_name: str) -> frozenset[str]:
    # `coder config-ssh` writes a `coder.<name>` alias and a `<name>.coder` host suffix,
    # and a machine someone added in Herdr by hand can use either one.
    return frozenset({_ssh_host_alias(workspace_name), f"{workspace_name}.coder"})


def ensure_machine(workspace_name: str) -> str:
    """Return the `hc` machine name for the devbox, adding the machine when it's missing."""
    targets = _ssh_targets(workspace_name)
    target = _ssh_host_alias(workspace_name)
    listing = _run_json(
        ["hc", "machine", "ls", "--json"],
        failure="Couldn't list Herdr machines.",
        cause="herdr_machine_list_failed",
    )
    for machine in listing.get("machines", []):
        if machine.get("target") in targets and machine.get("name"):
            _wait_until_connected(machine["name"])
            return machine["name"]

    click.echo(f"Adding '{workspace_name}' to Herdr. The first time, this copies hc onto the devbox...")
    result = _run(
        ["hc", "machine", "add", target, "--name", workspace_name, "--install", "--json"],
        timeout=_MACHINE_ADD_TIMEOUT,
    )
    if result.returncode != 0:
        _fail(
            f"Couldn't add '{workspace_name}' to Herdr.\n{_output_of(result)}",
            cause="herdr_machine_add_failed",
        )
    _wait_until_connected(workspace_name)
    return workspace_name


def _list_machines() -> list[dict[str, Any]] | None:
    result = _run(["hc", "machine", "ls", "--json"])
    if result.returncode != 0:
        return None
    try:
        machines = json.loads(result.stdout).get("machines", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    return [machine for machine in machines if isinstance(machine, dict)] if isinstance(machines, list) else None


def _machine_state(name: str) -> str | None:
    machines = _list_machines() or []
    return next((m.get("state") for m in machines if m.get("name") == name), None)


def forget_machine(workspace_name: str) -> None:
    """Remove the `hc` machine of a devbox that was just deleted, so Herdr stops trying to reach it.

    It never fails, because it runs after the devbox is already gone.
    """
    if shutil.which("hc") is None:
        return
    targets = _ssh_targets(workspace_name)
    machines = _list_machines()
    if machines is None:
        click.echo(
            f"  ⚠️  could not list Herdr machines to remove '{workspace_name}'. "
            "Check `hc machine ls` and remove its machine with `hc machine rm <name>`."
        )
        return
    for machine in machines:
        name = machine.get("name")
        if machine.get("target") not in targets or not name:
            continue
        if _run(["hc", "machine", "rm", name]).returncode == 0:
            click.echo(f"Removed '{name}' from Herdr.")
        else:
            click.echo(f"  ⚠️  could not remove '{name}' from Herdr. Run `hc machine rm {name}`.")


def _wait_until_connected(name: str) -> None:
    # `hc machine add` returns while the machine is still connecting, and a
    # saved machine reconnects for a while after its devbox starts. The Herdr
    # window refuses a space on a machine it hasn't seen connect.
    deadline = time.monotonic() + _MACHINE_CONNECT_TIMEOUT
    while _machine_state(name) != "connected":
        if time.monotonic() >= deadline:
            _fail(
                f"Herdr couldn't connect to '{name}'. Check `hc machine ls`, then run this command again.",
                cause="herdr_machine_connect_timeout",
            )
        time.sleep(_POLL_INTERVAL)


def _window_running() -> bool:
    return _run(["herdr-app", "status"]).returncode == 0


def ensure_window() -> None:
    """Open the Herdr window when it isn't running, and wait until it answers commands."""
    if _window_running():
        return

    click.echo("Opening Herdr...")
    subprocess.Popen(
        ["herdr-app"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.monotonic() + _WINDOW_START_TIMEOUT
    while time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
        if _window_running():
            return
    _fail(
        "Herdr didn't open in time. Open it yourself, then run this command again.",
        cause="herdr_window_timeout",
    )


def _do(command: str, args: dict[str, Any], *, retry_for: float = 0.0) -> None:
    deadline = time.monotonic() + retry_for
    while True:
        result = _run(["herdr-app", "do", command, json.dumps(args)])
        if result.returncode == 0:
            return
        if time.monotonic() >= deadline:
            _fail(f"Herdr couldn't run {command}.\n{_output_of(result)}", cause="herdr_command_failed")
        time.sleep(_POLL_INTERVAL)


def show_space(machine: str, *, name: str, folder: str) -> bool:
    """Show the machine's Herdr space, making one when none exists. Returns whether one was made."""
    listing = _run_json(
        ["herdr-app", "ls"],
        failure="Couldn't read the spaces in the Herdr window.",
        cause="herdr_ls_failed",
    )
    for space in listing.get("spaces", []):
        if space.get("machine") == machine and space.get("id"):
            _do("space.select", {"id": space["id"]})
            return False

    # The window learns about a machine from herdr-core shortly after hc
    # reports it connected, so a just-added machine can be briefly unknown.
    _do("space.new", {"name": name, "machine": machine, "folder": folder}, retry_for=_WINDOW_SEES_MACHINE_TIMEOUT)
    return True


def open_in_herdr(workspace_name: str, *, folder: str) -> None:
    """Register the devbox with Herdr and show a space for it."""
    _require_cli("hc")
    _require_cli("herdr-app")
    machine = ensure_machine(workspace_name)
    ensure_window()
    if show_space(machine, name=workspace_name, folder=folder):
        click.echo(f"Opened a Herdr space on '{workspace_name}' in {folder}.")
    else:
        click.echo(f"Showing the Herdr space for '{workspace_name}'.")


def _find_plugin(listing: Any) -> dict[str, Any] | None:
    if isinstance(listing, dict):
        if listing.get("plugin_id") == PLUGIN_ID:
            return listing
        children: list[Any] = list(listing.values())
    elif isinstance(listing, list):
        children = listing
    else:
        return None
    for child in children:
        found = _find_plugin(child)
        if found is not None:
            return found
    return None


def link_worktree_plugin(main_checkout: Path | None) -> None:
    """Link the plugin from *main_checkout*, which outlives every worktree, unless herdr already has it."""
    herdr = shutil.which("herdr")
    if herdr is None:
        click.echo(f"herdr isn't on your PATH. Once it is, run `herdr plugin link <main checkout>/{PLUGIN_DIR}`.")
        return
    try:
        listing = subprocess.run([herdr, "plugin", "list", "--json"], capture_output=True, text=True, timeout=30)
        existing = _find_plugin(json.loads(listing.stdout)) if listing.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        existing = None
    if existing is not None:
        state = "enabled" if existing.get("enabled") else "disabled"
        click.echo(f"The herdr plugin {PLUGIN_ID} is already linked from {existing.get('plugin_root')} ({state}).")
        return
    if main_checkout is None:
        click.echo(f"Couldn't find your main checkout. Run `herdr plugin link <main checkout>/{PLUGIN_DIR}`.")
        return
    plugin_dir = main_checkout / PLUGIN_DIR
    if not (plugin_dir / "herdr-plugin.toml").is_file():
        click.echo(f"Your main checkout has no {PLUGIN_DIR} yet. Pull it, then run this command again.")
        return
    try:
        result = subprocess.run([herdr, "plugin", "link", str(plugin_dir)], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        click.echo(f"Couldn't link the herdr plugin: {error}")
        return
    if result.returncode != 0:
        click.echo(f"Couldn't link the herdr plugin: {(result.stderr or result.stdout).strip()}")
        return
    click.echo(f"Linked the herdr plugin from {plugin_dir}. Turn it off with `herdr plugin disable {PLUGIN_ID}`.")
