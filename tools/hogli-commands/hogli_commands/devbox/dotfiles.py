"""Apply your dotfiles on a devbox again, for a box that couldn't clone them when it started."""

from __future__ import annotations

import click

from .cli import (
    _ensure_ssh_alias,
    _skip_startup_wait,
    _targets_own_box,
    remote_apply_dotfiles,
    resolve_workspace_name,
    workspace_argument,
)
from .coder import _fail, ensure_runtime_ready, exec_replace, workspace_dotfiles_uri


@click.command(
    name="devbox:dotfiles",
    help="Apply your dotfiles repo on your devbox again. A private repo needs `hogli devbox:gh:login` first",
)
@workspace_argument
def devbox_dotfiles(workspace: str | None) -> None:
    """Run `coder dotfiles` on the box with the dotfiles repo the box was built with."""
    if not _targets_own_box(workspace):
        _fail("Apply dotfiles only on your own devbox.")
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    uri = workspace_dotfiles_uri(name)
    if not uri:
        _fail(
            f"'{name}' was built without a dotfiles repo. Run `hogli devbox:setup --configure-dotfiles`, "
            "and new devboxes get it."
        )
    _ensure_ssh_alias(name)
    _skip_startup_wait()
    click.echo(f"Applying {uri} on '{name}'.")
    exec_replace(name, remote_apply_dotfiles(uri))
