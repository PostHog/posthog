"""Report which per-box setup a devbox still needs, such as the logins that live on the box's disk.

Each check is one entry in ``BOX_CHECKS``. All probes run on the box in one SSH round trip.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Literal

import click

from .cli import (
    DOTFILES_FAILED_ON_BOX,
    TRUNK_MISSING_EXIT,
    _ensure_ssh_alias,
    _remote_claude_auth,
    _skip_startup_wait,
    _targets_own_box,
    _workspace_arg_suffix,
    remote_trunk,
    resolve_workspace_name,
    workspace_argument,
)
from .coder import _fail, coder_ssh_alias_configured, ensure_runtime_ready, run_in_workspace

_MARKER = "HOGLI_CHECK"
_PROBE_TIMEOUT_SECONDS = 15
_ALL_PROBES_TIMEOUT_SECONDS = 30

CheckState = Literal["ready", "missing", "unknown"]


# hogli-commands doesn't depend on the posthog package, so `posthog.dataclasses.frozen` isn't importable here.
@dataclass(frozen=True, kw_only=True, slots=True)
class BoxCheck:
    label: str
    # A bash snippet that runs on the box and exits 0 when the setup is done and 1 when it is missing.
    # Any other exit means hogli can't tell.
    probe: str
    # The command that fixes a missing setup. "{target}" becomes the argument that names the box.
    fix: str
    # Other probe exits that also mean missing, each with its own fix.
    other_fixes: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True, slots=True)
class BoxCheckResult:
    check: BoxCheck
    state: CheckState
    fix: str | None = None


BOX_CHECKS: tuple[BoxCheck, ...] = (
    BoxCheck(
        label="Claude Code login",
        # A CLAUDE_CODE_OAUTH_TOKEN that reaches the box also reports loggedIn.
        probe=f"{shlex.join(_remote_claude_auth('status', '--json'))} | grep -q '\"loggedIn\": *true'",
        fix="hogli devbox:claude:login{target}",
    ),
    BoxCheck(
        label="GitHub CLI login",
        # Unlike remote_gh_auth, this keeps GH_TOKEN, because a token secret also makes gh work.
        probe=shlex.join(["gh", "auth", "status", "--hostname", "github.com"]),
        fix="hogli devbox:gh:login{target}",
    ),
    BoxCheck(
        label="Trunk CLI login",
        probe=shlex.join(remote_trunk("whoami", "--no-progress")),
        fix="hogli devbox:trunk:login{target}",
        other_fixes={
            TRUNK_MISSING_EXIT: "hogli devbox:exec{target} --flox -- true, then hogli devbox:trunk:login{target}",
        },
    ),
    BoxCheck(
        label="Dotfiles",
        # A box without a dotfiles repo has no failure in its log, so it counts as set up.
        probe=f"! {{ {DOTFILES_FAILED_ON_BOX}; }}",
        fix="hogli devbox:dotfiles{target}",
    ),
)


def build_probe_script(checks: tuple[BoxCheck, ...]) -> str:
    """Return a bash script that runs every probe at once and prints one marked line per check."""
    lines = []
    for index, check in enumerate(checks):
        probe = shlex.quote(check.probe)
        lines.append(
            f'( timeout {_PROBE_TIMEOUT_SECONDS} bash -c {probe} >/dev/null 2>&1; echo "{_MARKER} {index} $?" ) &'
        )
    lines.append("wait")
    return "\n".join(lines)


def parse_probe_output(output: str, checks: tuple[BoxCheck, ...], target: str) -> list[BoxCheckResult]:
    # The login shell profile on the box can print anything before the probes run, so only marked lines count.
    exits: dict[int, int] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == _MARKER and parts[1].isdigit() and parts[2].isdigit():
            exits[int(parts[1])] = int(parts[2])

    results = []
    for index, check in enumerate(checks):
        exit_code = exits.get(index)
        if exit_code == 0:
            results.append(BoxCheckResult(check=check, state="ready"))
        elif exit_code == 1:
            results.append(BoxCheckResult(check=check, state="missing", fix=check.fix.format(target=target)))
        elif exit_code in check.other_fixes:
            fix = check.other_fixes[exit_code].format(target=target)
            results.append(BoxCheckResult(check=check, state="missing", fix=fix))
        else:
            results.append(BoxCheckResult(check=check, state="unknown"))
    return results


def run_box_checks(name: str) -> list[BoxCheckResult] | None:
    """Run every check on the box, or return ``None`` when the box doesn't answer."""
    _skip_startup_wait()
    script = build_probe_script(BOX_CHECKS)
    try:
        result = run_in_workspace(name, ["bash", "-c", script], timeout=_ALL_PROBES_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if _MARKER not in result.stdout:
        return None
    return parse_probe_output(result.stdout, BOX_CHECKS, _workspace_arg_suffix(name))


def print_box_checks(results: list[BoxCheckResult]) -> None:
    missing = [result for result in results if result.state == "missing"]
    unknown = [result for result in results if result.state == "unknown"]
    if not missing and not unknown:
        labels = ", ".join(result.check.label for result in results)
        click.echo(f"Box setup: {labels} are ready.")
        return
    click.echo("Box setup:")
    for result in missing:
        click.echo(click.style(f"  Missing {result.check.label}. Run `{result.fix}`.", fg="yellow"))
    for result in unknown:
        click.echo(f"  Couldn't check {result.check.label}.")


def report_box_setup(name: str) -> None:
    """Print what the box still needs. Never fails, because `devbox:start` calls it after the box is up."""
    if not coder_ssh_alias_configured(name):
        return
    click.echo()
    results = run_box_checks(name)
    if results is None:
        click.echo("Couldn't check box setup.")
        return
    print_box_checks(results)


@click.command(name="devbox:check", help="Show which logins and other per-box setup your devbox is missing")
@workspace_argument
def devbox_check(workspace: str | None) -> None:
    if not _targets_own_box(workspace):
        _fail("Check box setup only on your own devbox.")
    ensure_runtime_ready()
    name, _ = resolve_workspace_name(workspace)
    _ensure_ssh_alias(name)
    results = run_box_checks(name)
    if results is None:
        _fail(f"Couldn't check '{name}'. Check that the devbox runs with `hogli devbox:status`.")
    print_box_checks(results)
