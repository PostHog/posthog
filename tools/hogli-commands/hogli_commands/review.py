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
nonzero, leaving the PR bot as the reviewer. On a stacked branch, pass
``-b <base>`` so the walk covers only this layer's commits.

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
from hogli.manifest import REPO_ROOT

from hogli_commands import posthog_auth

EX_CONFIG = posthog_auth.EXIT_NOT_CONFIGURED

_INSTALL_HINT = (
    "Re-enter the flox environment (activation installs it), "
    "or install it with `brew install greptileai/tap/greptile` or `npm install -g greptile`, then re-run."
)
_SIGNIN_HINT = (
    "Run `greptile login`, or set GREPTILE_API_KEY in .env.local (see .env.local.example). "
    "No access? The reviewing-before-pr skill has a harness-review fallback."
)

# From the Greptile CLI reference for `review status`: exit 0 means a completed
# review exists for the commit, 3 means one is still running.
_STATUS_COMPLETED = 0
_STATUS_RUNNING = 3

# The probes are short subprocess calls; the review itself runs uncapped
# because a large diff legitimately takes minutes.
_PROBE_TIMEOUT_SECONDS = 60

# Newest-first probe window for --check. Each probe is a network call, and the
# gate only asserts "the local loop ran on this branch", so a hit is expected
# within the last few commits.
_CHECK_COMMIT_LIMIT = 20


def _probe(cmd: list[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None


def _signed_in(binary: str) -> bool:
    """False only on Greptile's explicit signed-out error; any other ``config``
    failure falls through to the review call, which reports the real problem.
    The string match is forced: greptile exits 1 for signed-out and for
    ordinary failures alike."""
    result = _probe([binary, "config"])
    return result is None or result.returncode == 0 or "not signed in" not in (result.stdout + result.stderr).lower()


def _branch_commits(base: str | None) -> list[str]:
    # Match change_detection's base convention: origin/master, then master for
    # clones without the remote ref.
    for ref in [base] if base is not None else ["origin/master", "master"]:
        result = _probe(["git", "-C", str(REPO_ROOT), "rev-list", f"--max-count={_CHECK_COMMIT_LIMIT}", f"{ref}..HEAD"])
        if result is not None and result.returncode == 0:
            return result.stdout.split() or ["HEAD"]
    return ["HEAD"]


def check(binary: str, base: str | None) -> int:
    for commit in _branch_commits(base):
        status = _probe([binary, "review", "status", "--commit", commit])
        if status is None:
            # A hung or broken probe would hang or break for every commit too.
            break
        if status.returncode == _STATUS_COMPLETED:
            click.secho(
                f"Commit {commit[:11]} has a completed review. Open the PR with `--label no-greptile`.",
                fg="green",
                err=True,
            )
            return 0
    click.secho("No commit on this branch has a completed review.", fg="yellow", err=True)
    return 1


def run(branch: str | None, instructions: str | None, force: bool, do_check: bool) -> int:
    binary = shutil.which("greptile")
    if binary is None:
        click.secho(f"Greptile CLI not found. {_INSTALL_HINT}", fg="red", err=True)
        return 1
    if not _signed_in(binary):
        click.secho(f"Not signed in to Greptile. {_SIGNIN_HINT}", fg="yellow", err=True)
        return EX_CONFIG
    if do_check:
        return check(binary, branch)

    if not force:
        status = _probe([binary, "review", "status", "--commit", "HEAD"])
        if status is not None and status.returncode == _STATUS_COMPLETED:
            click.secho(
                "HEAD already has a completed review. Showing it. Pass --force to start a new one.",
                fg="cyan",
                err=True,
            )
            click.echo(status.stdout, nl=False)
            return 0
        if status is not None and status.returncode == _STATUS_RUNNING:
            click.secho("A review for this branch is still running. Resuming it.", fg="cyan", err=True)
            return subprocess.run([binary, "review", "--resume"]).returncode

    cmd = [binary, "review"]
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
@click.option(
    "--check",
    "do_check",
    is_flag=True,
    help="Only report whether any commit on this branch has a completed review (exit 0 when one does); reviews nothing.",
)
def review(branch: str | None, instructions: str | None, force: bool, do_check: bool) -> None:
    raise SystemExit(run(branch, instructions, force, do_check))
