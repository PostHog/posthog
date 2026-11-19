"""Log the Trunk CLI in on a devbox, so `trunk merge` can put pull requests in the merge queue from there."""

from __future__ import annotations

import subprocess

import click

from .cli import (
    _TRUNK_AUTH_TIMEOUT,
    TRUNK_LOGIN_WITHOUT_CLI_EXIT,
    TRUNK_MISSING_EXIT,
    _ensure_ssh_alias,
    _skip_startup_wait,
    _targets_own_box,
    logout_trunk,
    read_trunk_login,
    remote_trunk,
    resolve_workspace_name,
    workspace_argument,
)
from .coder import _fail, ensure_runtime_ready, exec_replace, get_workspace_shares, run_in_workspace


def _box(workspace: str | None) -> str:
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    _ensure_ssh_alias(name)
    _skip_startup_wait()
    return name


def _fail_without_trunk(name: str) -> None:
    try:
        result = run_in_workspace(name, remote_trunk("--version"), timeout=_TRUNK_AUTH_TIMEOUT)
    except subprocess.TimeoutExpired:
        _fail(f"'{name}' didn't answer. Check that the devbox runs with `hogli devbox:status`.")
    if result.returncode in (TRUNK_MISSING_EXIT, TRUNK_LOGIN_WITHOUT_CLI_EXIT):
        _fail(
            f"Couldn't find the Trunk CLI on '{name}'. It comes with PostHog's flox environment, so run "
            "`hogli devbox:exec --flox -- true` once to set that up, then run this command again."
        )


@click.command(name="devbox:trunk:login", help="Log the Trunk CLI in on your devbox, for the merge queue")
@workspace_argument
def devbox_trunk_login(workspace: str | None) -> None:
    """Run `trunk login` on the box.

    trunk prints a link to open on this computer. The login stays on the box's disk until
    `devbox:trunk:logout` or `devbox:destroy`.
    """
    if not _targets_own_box(workspace):
        _fail("Log in to Trunk only on your own devbox.")
    name = _box(workspace)
    shares = get_workspace_shares(name)
    if shares is None:
        _fail(f"Couldn't check who '{name}' is shared with. Run the command again.")
    if shares:
        _fail(
            f"'{name}' is shared with {', '.join(shares)}, who could use a Trunk login stored there. "
            "Run `hogli devbox:unshare` and restart the box first."
        )
    _fail_without_trunk(name)
    click.echo(f"Logging the Trunk CLI in on '{name}'. Open the link it prints to finish.")
    # ssh gives the remote command no terminal, so trunk prints a device login link and waits.
    exec_replace(name, remote_trunk("login"))


@click.command(name="devbox:trunk:status", help="Show which Trunk account the Trunk CLI on your devbox uses")
@workspace_argument
def devbox_trunk_status(workspace: str | None) -> None:
    name = _box(workspace)
    login = read_trunk_login(name)
    if login is None:
        _fail(f"Couldn't read the Trunk CLI login on '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    if not login:
        click.echo(f"The Trunk CLI on '{name}' isn't logged in. Run `hogli devbox:trunk:login`.")
        return
    click.echo(login)


@click.command(name="devbox:trunk:logout", help="Log the Trunk CLI out on your devbox")
@workspace_argument
def devbox_trunk_logout(workspace: str | None) -> None:
    """Run `trunk logout` on the box, which deletes the token stored there."""
    name = _box(workspace)
    login = read_trunk_login(name)
    if login is None:
        _fail(f"Couldn't read the Trunk CLI login on '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    if not login:
        click.echo(f"The Trunk CLI on '{name}' isn't logged in.")
        return
    if not logout_trunk(name):
        _fail(f"Couldn't log the Trunk CLI out on '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    click.echo(f"Logged the Trunk CLI out on '{name}'.")
