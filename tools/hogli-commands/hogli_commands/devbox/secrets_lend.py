"""Lend 1Password secrets to a devbox for a limited time, kept in the box's memory only.

The laptop resolves `op://` references with one 1Password unlock and sends the values over
SSH stdin. The box keeps them in /dev/shm, and `devbox-secrets run -- <command>` hands them
to one command at a time, the way `op run` does locally.
"""

from __future__ import annotations

import os
import re
import time
import subprocess
from pathlib import Path

import click

from .cli import resolve_workspace_name, workspace_argument
from .coder import _fail, _ssh_host_alias, coder_ssh_alias_configured, ensure_runtime_ready

REFERENCES_FILE = Path.home() / ".config" / "posthog" / "devbox-secrets.env"
BOX_SCRIPT = Path(__file__).with_name("devbox-secrets.sh")
REMOTE_SCRIPT = ".local/bin/devbox-secrets"
_SSH_TIMEOUT = 60
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _read_references(path: Path) -> list[tuple[str, str]]:
    """Return ``(NAME, op://reference)`` pairs from the references file."""
    if not path.exists():
        _fail(
            f"No references file at {path}. Add lines like OPENAI_API_KEY=op://<vault>/<item>/<field>, then run this again."
        )
    references = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reference = line.partition("=")
        if not _NAME.match(name) or not reference.startswith("op://"):
            _fail(f"Can't read this line in {path}: {name}=… Use NAME=op://<vault>/<item>/<field>.")
        references.append((name, reference))
    if not references:
        _fail(f"{path} lists no references.")
    return references


def _resolve(references: list[tuple[str, str]]) -> str:
    """Resolve every reference with one `op inject`, so 1Password asks once."""
    template = "".join(f"{name}={{{{ {reference} }}}}\n" for name, reference in references)
    try:
        result = subprocess.run(["op", "inject"], input=template, capture_output=True, text=True)
    except OSError:
        _fail("The 1Password CLI (`op`) isn't installed on this computer.")
    if result.returncode != 0:
        _fail(f"1Password couldn't resolve the references: {result.stderr.strip()}")
    return result.stdout


def _ssh(name: str, remote_command: str, stdin: str) -> subprocess.CompletedProcess[str]:
    # Coder's ssh proxy otherwise waits for blocking startup scripts and replays their log.
    env = {**os.environ, "CODER_SSH_WAIT": os.environ.get("CODER_SSH_WAIT", "no")}
    try:
        return subprocess.run(
            ["ssh", _ssh_host_alias(name), remote_command],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_SSH_TIMEOUT,
            env=env,
        )
    except subprocess.TimeoutExpired:
        _fail(f"'{name}' didn't answer. Check that the devbox runs with `hogli devbox:status`.")


def _box(workspace: str | None) -> str:
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    if not coder_ssh_alias_configured(name):
        _fail("SSH isn't set up for devboxes yet. Run `hogli devbox:setup` first.")
    return name


def _install_box_script(name: str) -> None:
    result = _ssh(
        name,
        f"mkdir -p ~/.local/bin && cat > ~/{REMOTE_SCRIPT}.new && chmod 755 ~/{REMOTE_SCRIPT}.new "
        f"&& mv ~/{REMOTE_SCRIPT}.new ~/{REMOTE_SCRIPT}",
        BOX_SCRIPT.read_text(),
    )
    if result.returncode != 0:
        _fail(f"Couldn't install devbox-secrets on '{name}': {result.stderr.strip()}")


def _run_box_script(name: str, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
    return _ssh(name, " ".join([f"~/{REMOTE_SCRIPT}", *args]), stdin)


@click.command(
    name="devbox:secrets:push", help="Lend 1Password secrets to your devbox, in memory and for a limited time"
)
@workspace_argument
@click.option("--hours", default=12, show_default=True, type=click.IntRange(1, 72), help="How long the box keeps them")
@click.option(
    "--file",
    "references_file",
    type=click.Path(path_type=Path, dir_okay=False),
    default=REFERENCES_FILE,
    show_default=True,
    help="NAME=op://… references to lend",
)
def devbox_secrets_push(workspace: str | None, hours: int, references_file: Path) -> None:
    name = _box(workspace)
    references = _read_references(references_file)
    values = _resolve(references)
    _install_box_script(name)
    expires = int(time.time()) + hours * 3600
    result = _run_box_script(name, "store", str(expires), stdin=values)
    if result.returncode != 0:
        _fail(f"Couldn't store the secrets on '{name}': {result.stderr.strip()}")
    names = ", ".join(n for n, _ in references)
    click.echo(f"Lent {names} to '{name}' for {hours}h. They're in memory only and go when the box stops.")
    click.echo("On the box: devbox-secrets run -- <command>")


@click.command(name="devbox:secrets:status", help="Show which secrets your devbox holds and for how long")
@workspace_argument
def devbox_secrets_status(workspace: str | None) -> None:
    name = _box(workspace)
    result = _run_box_script(name, "status")
    if result.returncode == 127:
        click.echo(f"No secrets lent to '{name}'.")
        return
    click.echo(result.stdout.strip() or result.stderr.strip())


@click.command(name="devbox:secrets:clear", help="Remove lent secrets from your devbox now")
@workspace_argument
def devbox_secrets_clear(workspace: str | None) -> None:
    name = _box(workspace)
    result = _run_box_script(name, "clear")
    if result.returncode == 127:
        click.echo(f"No secrets lent to '{name}'.")
        return
    if result.returncode != 0:
        _fail(f"Couldn't clear the secrets on '{name}': {result.stderr.strip()}")
    click.echo(f"Cleared the lent secrets on '{name}'.")
