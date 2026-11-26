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
from dataclasses import dataclass
from pathlib import Path

import click

from .cli import _targets_own_box, resolve_workspace_name, workspace_argument
from .coder import _fail, _ssh_host_alias, coder_ssh_alias_configured, ensure_runtime_ready, get_workspace_shares

REFERENCES_FILE = Path.home() / ".config" / "posthog" / "devbox-secrets.env"
BOX_SCRIPT = Path(__file__).with_name("devbox-secrets.sh")
REMOTE_SCRIPT = ".local/bin/devbox-secrets"
_SSH_TIMEOUT = 60
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class SecretReference:
    name: str
    reference: str


def _read_references(path: Path) -> list[SecretReference]:
    """Return the ``NAME=op://…`` lines of the references file."""
    if not path.exists():
        _fail(
            f"No references file at {path}. Add lines like OPENAI_API_KEY=op://<vault>/<item>/<field>, then run this again."
        )
    references = []
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, reference = line.partition("=")
        if not _NAME.match(name) or not reference.startswith("op://"):
            # Never echo the line: a pasted value would land in the terminal or an agent's log.
            _fail(f"Line {number} of {path} isn't NAME=op://<vault>/<item>/<field>.")
        references.append(SecretReference(name=name, reference=reference))
    if not references:
        _fail(f"{path} lists no references.")
    return references


def _resolve(references: list[SecretReference]) -> str:
    """Resolve every reference with one `op inject`, so 1Password asks once."""
    template = "".join(f"{r.name}={{{{ {r.reference} }}}}\n" for r in references)
    try:
        result = subprocess.run(["op", "inject"], input=template, capture_output=True, text=True)
    except OSError:
        _fail("The 1Password CLI (`op`) isn't installed on this computer.")
    if result.returncode != 0:
        _fail(f"1Password couldn't resolve the references: {result.stderr.strip()}")
    # The box reads one NAME=value per line, so a value with a line break would turn its next line into
    # a variable name that `status` prints.
    lines = result.stdout.splitlines()
    for index, reference in enumerate(references):
        if index >= len(lines) or not lines[index].startswith(f"{reference.name}="):
            multi_line = references[max(index - 1, 0)].name
            _fail(f"The value of {multi_line} has more than one line. Lend single-line values only.")
    if len(lines) != len(references):
        _fail(f"The value of {references[-1].name} has more than one line. Lend single-line values only.")
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


def _refuse_shared_box(name: str) -> None:
    """Fail unless only the owner can open the box: anyone it is shared with gets a shell as the owner."""
    shares = get_workspace_shares(name)
    if shares is None:
        _fail(f"Couldn't check who '{name}' is shared with. Run the command again.")
    if shares:
        _fail(
            f"'{name}' is shared with {', '.join(shares)}, who could read lent secrets. Run `hogli devbox:unshare` first."
        )


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
    if not _targets_own_box(workspace):
        _fail("Lend secrets only to your own devbox.")
    name = _box(workspace)
    _refuse_shared_box(name)
    references = _read_references(references_file)
    values = _resolve(references)
    _install_box_script(name)
    # The 1Password unlock can take a while, so check again right before the values reach the box.
    _refuse_shared_box(name)
    expires = int(time.time()) + hours * 3600
    result = _run_box_script(name, "store", str(expires), stdin=values)
    if result.returncode != 0:
        _fail(f"Couldn't store the secrets on '{name}': {result.stderr.strip()}")
    names = ", ".join(r.name for r in references)
    click.echo(f"Lent {names} to '{name}' for {hours}h. They're in memory only and go when the box stops.")
    click.echo("On the box: devbox-secrets run -- <command>")


@click.command(name="devbox:secrets:status", help="Show which secrets your devbox holds and for how long")
@workspace_argument
def devbox_secrets_status(workspace: str | None) -> None:
    name = _box(workspace)
    # A missing script must not read as "nothing lent" while the store is still in /dev/shm.
    _install_box_script(name)
    result = _run_box_script(name, "status")
    if result.returncode != 0:
        _fail(f"Couldn't check the secrets on '{name}': {result.stderr.strip()}")
    click.echo(result.stdout.strip())


@click.command(name="devbox:secrets:clear", help="Remove lent secrets from your devbox now")
@workspace_argument
def devbox_secrets_clear(workspace: str | None) -> None:
    name = _box(workspace)
    _install_box_script(name)
    result = _run_box_script(name, "clear")
    if result.returncode != 0:
        _fail(f"Couldn't clear the secrets on '{name}': {result.stderr.strip()}")
    click.echo(f"Cleared the lent secrets on '{name}'.")
