"""One local Greptile review of the branch, before its PR opens.

``hogli review`` wraps the Greptile CLI. Greptile already reviews every PostHog
PR after it opens; running the first pass locally turns its findings into
pre-push edits instead of bot comments, stale-thread cleanup, and CI re-runs.

    hogli review                        # review committed changes vs the repo default base
    hogli review --instructions "..."   # focus the reviewer, like an @greptile PR comment
    hogli review --force                # start a new review even when HEAD has one
    hogli review --check                # exit 0 when any branch commit has a completed review

``--check`` gates the ``no-greptile`` PR label: a completed review anywhere on
the branch means the local loop ran, and the label skips the duplicate bot
pass even when fix commits landed after the review. Only a branch no review
ever ran on (or a state where that cannot be told: signed out, no CLI) exits
nonzero, leaving the PR bot as the reviewer.

On top of ``greptile review`` itself, the wrapper:

- skips the paid review when HEAD already has a completed one (re-printing it)
  and resumes one still in progress, so "review once before opening the PR"
  stays once across agent retries; ``--force`` overrides.
- exits ``78`` (sysexits ``EX_CONFIG``) with setup guidance when not signed in,
  matching ``ci:insights`` so skills branch on the exit code, not message text.

Greptile reviews committed changes only, so commit everything first. The
reviewing-before-pr skill covers where this sits in the PR-opening flow.
"""

from __future__ import annotations

import shutil
import subprocess

import click

EX_CONFIG = 78

_INSTALL_HINT = (
    "Re-enter the flox environment (activation installs it), "
    "or install it with `brew install greptileai/tap/greptile` or `npm install -g greptile`, then re-run."
)
_SIGNIN_HINT = "Run `greptile login`, or set GREPTILE_API_KEY in .env.local (op:// references resolve there)."

# From the Greptile CLI reference for `review status`: exit 0 means a completed
# review exists for the commit, 3 means one is still running.
_STATUS_COMPLETED = 0
_STATUS_RUNNING = 3

# The probes are one config read and one status lookup; the review itself runs
# uncapped because a large diff legitimately takes minutes.
_PROBE_TIMEOUT_SECONDS = 60


def _probe(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None


def _signed_in(binary: str) -> bool:
    """False only on Greptile's explicit signed-out error. Any other ``config``
    failure falls through to the review call, which reports the real problem."""
    result = _probe([binary, "config"])
    if result is None or result.returncode == 0:
        return True
    return "not signed in" not in (result.stdout + result.stderr).lower()


# Newest-first probe cap: a branch this deep is stacked wrong long before the
# cap matters, and each probe is a network call.
_CHECK_COMMIT_LIMIT = 100


def _branch_commits() -> list[str]:
    result = _probe(["git", "rev-list", f"--max-count={_CHECK_COMMIT_LIMIT}", "origin/master..HEAD"])
    if result is None or result.returncode != 0:
        return ["HEAD"]
    return result.stdout.split() or ["HEAD"]


def check(binary: str) -> int:
    for commit in _branch_commits():
        status = _probe([binary, "review", "status", "--commit", commit])
        if status is not None and status.returncode == _STATUS_COMPLETED:
            click.secho(f"Commit {commit[:11]} has a completed review.", fg="green", err=True)
            return 0
    click.secho("No commit on this branch has a completed review.", fg="yellow", err=True)
    return 1


def run(branch: str | None, instructions: str | None, force: bool, as_json: bool, do_check: bool) -> int:
    binary = shutil.which("greptile")
    if binary is None:
        click.secho(f"Greptile CLI not found. {_INSTALL_HINT}", fg="red", err=True)
        return 1
    if not _signed_in(binary):
        click.secho(f"Not signed in to Greptile. {_SIGNIN_HINT}", fg="yellow", err=True)
        return EX_CONFIG
    if do_check:
        return check(binary)

    output_flags = ["--json"] if as_json else []
    resume = False
    if not force:
        status = _probe([binary, "review", "status", "--commit", "HEAD", *output_flags])
        if status is not None and status.returncode == _STATUS_COMPLETED:
            click.secho(
                "HEAD already has a completed review. Showing it. Pass --force to start a new one.",
                fg="cyan",
                err=True,
            )
            click.echo(status.stdout, nl=False)
            return 0
        resume = status is not None and status.returncode == _STATUS_RUNNING

    cmd = [binary, "review", *output_flags]
    if resume:
        click.secho("A review for this branch is still running. Resuming it.", fg="cyan", err=True)
        cmd.append("--resume")
    else:
        if branch is not None:
            cmd += ["--branch", branch]
        if instructions is not None:
            cmd += ["--instructions", instructions]
    # Inherit stdio so Greptile's own progress and interactive review view work.
    return subprocess.run(cmd).returncode


@click.command(
    name="review",
    help="One local Greptile review of the branch, before you open the PR or mark it ready.",
)
@click.option("-b", "--branch", default=None, help="Base branch to review against. Omit to use the repository default.")
@click.option("--instructions", default=None, help="Extra instructions for this review, like an @greptile PR comment.")
@click.option("--force", is_flag=True, help="Start a new review even when HEAD already has a completed one.")
@click.option("--json", "as_json", is_flag=True, help="Print review comments as JSON.")
@click.option(
    "--check",
    "do_check",
    is_flag=True,
    help="Only report whether any commit on this branch has a completed review (exit 0 when one does); reviews nothing.",
)
def review(branch: str | None, instructions: str | None, force: bool, as_json: bool, do_check: bool) -> None:
    raise SystemExit(run(branch, instructions, force, as_json, do_check))
