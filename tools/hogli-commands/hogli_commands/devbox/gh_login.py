"""Log the GitHub CLI in on a devbox, for `gh` and for git.

Coder hands SSH sessions a GitHub token through GIT_ASKPASS. Only git uses it, and it reaches only the
repositories where Coder's GitHub app is installed. A `gh` login stored on the box works for every
process there, including ones that outlive the SSH connection that started them, such as Herdr tabs.
"""

from __future__ import annotations

import shlex
import subprocess

import click

from .cli import (
    _GH_AUTH_TIMEOUT,
    DOTFILES_FAILED_ON_BOX,
    _ensure_ssh_alias,
    _skip_startup_wait,
    _targets_own_box,
    logout_gh,
    read_gh_logins,
    remote_apply_dotfiles,
    remote_gh_auth,
    resolve_workspace_name,
    workspace_argument,
)
from .coder import (
    _fail,
    ensure_runtime_ready,
    exec_replace,
    get_workspace_shares,
    run_in_workspace,
    server_supports_user_secrets,
    user_secret_exists,
    workspace_dotfiles_uri,
)

_DEVICE_URL = "https://github.com/login/device"


def _box(workspace: str | None) -> str:
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    _ensure_ssh_alias(name)
    _skip_startup_wait()
    return name


@click.command(name="devbox:gh:login", help="Log the GitHub CLI in on your devbox, for gh and git")
@workspace_argument
def devbox_gh_login(workspace: str | None) -> None:
    """Run `gh auth login` on the box, then `gh auth setup-git` so git uses the same login, then install gh stack.

    When the box couldn't clone a private dotfiles repo at start, this applies the dotfiles again.

    gh prints a one-time code to enter at https://github.com/login/device on this computer.
    The login stays on the box's disk until `devbox:gh:logout` or `devbox:destroy`.
    """
    if not _targets_own_box(workspace):
        _fail("Log in to GitHub only on your own devbox.")
    name = _box(workspace)
    shares = get_workspace_shares(name)
    if shares is None:
        _fail(f"Couldn't check who '{name}' is shared with. Run the command again.")
    if shares:
        _fail(
            f"'{name}' is shared with {', '.join(shares)}, who could use a GitHub login stored there. "
            "Run `hogli devbox:unshare` and restart the box first."
        )
    if server_supports_user_secrets() and user_secret_exists("GH_TOKEN"):
        click.echo(click.style("Your GH_TOKEN Coder user secret is set, and gh on the box uses it first.", fg="yellow"))
        click.echo("  Run `hogli devbox:secret:rm GH_TOKEN` and restart the box so gh uses this login.")
    click.echo(f"Logging the GitHub CLI in on '{name}'. Enter the code it prints at {_DEVICE_URL}.")
    # ssh gives the remote command no terminal, so gh prints the code and waits instead of asking
    # questions. The workflow scope lets git push branches that change .github/workflows.
    login = shlex.join(remote_gh_auth("login", "--git-protocol", "https", "--web", "--scopes", "workflow"))
    setup_git = shlex.join(remote_gh_auth("setup-git"))
    # gh stack is how this repo stacks pull requests. A failed install leaves the login in place.
    # The outer braces keep the fallback echo from also catching a failed login before it.
    install_gh_stack = (
        "{ { gh extension list | grep -q gh-stack || gh extension install github/gh-stack; } "
        '|| echo "Couldn\'t install gh stack. Run gh extension install github/gh-stack on the box."; }'
    )
    steps = [login, setup_git, install_gh_stack]
    dotfiles_uri = workspace_dotfiles_uri(name)
    if dotfiles_uri:
        # git can now read a private dotfiles repo that the box couldn't clone when it started.
        steps.append(
            f"if {DOTFILES_FAILED_ON_BOX}; then {shlex.join(remote_apply_dotfiles(dotfiles_uri))} "
            '|| echo "Couldn\'t apply your dotfiles. Run hogli devbox:dotfiles on your computer."; fi'
        )
    exec_replace(name, ["bash", "-c", " && ".join(steps)])


@click.command(name="devbox:gh:status", help="Show which GitHub account the GitHub CLI on your devbox uses")
@workspace_argument
def devbox_gh_status(workspace: str | None) -> None:
    """Print `gh auth status` from the box, which masks the token."""
    name = _box(workspace)
    try:
        result = run_in_workspace(name, ["gh", "auth", "status", "--hostname", "github.com"], timeout=_GH_AUTH_TIMEOUT)
    except subprocess.TimeoutExpired:
        _fail(f"'{name}' didn't answer. Check that the devbox runs with `hogli devbox:status`.")
    if result.returncode == 0:
        click.echo(result.stdout.strip())
        return
    if "not logged into any" in result.stdout + result.stderr:
        click.echo(f"The GitHub CLI on '{name}' isn't logged in. Run `hogli devbox:gh:login`.")
        return
    click.echo(result.stdout.strip())
    _fail(f"Couldn't read the GitHub CLI login on '{name}': {result.stderr.strip()}")


@click.command(name="devbox:gh:logout", help="Log the GitHub CLI out on your devbox")
@workspace_argument
def devbox_gh_logout(workspace: str | None) -> None:
    """Run `gh auth logout` on the box, which deletes the token stored there.

    git on the box then falls back to Coder's GitHub token.
    """
    name = _box(workspace)
    logins = read_gh_logins(name)
    if logins is None:
        _fail(f"Couldn't read the GitHub CLI login on '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    if not logins:
        click.echo(f"The GitHub CLI on '{name}' isn't logged in.")
        return
    if not logout_gh(name, logins):
        _fail(f"Couldn't log the GitHub CLI out on '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    click.echo(f"Logged the GitHub CLI out on '{name}'.")
    click.echo(
        "The token stays valid on GitHub. To revoke it, remove GitHub CLI under Settings > Applications "
        "on github.com, which also logs gh out on your other computers."
    )
