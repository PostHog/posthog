"""`hogli devbox:sync` -- one-way-safe local->remote file sync for Coder devboxes.

Lets engineers edit code locally while running the full PostHog dev stack
on a Coder devbox. Local is the source of truth; nothing flows back to local
automatically. Sessions are addressed by mutagen label, not name, so multiple
workspaces stay independently controllable.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import click

from . import mutagen
from .cli import _workspace_arg_suffix, resolve_workspace_name, workspace_argument
from .coder import _fail, ensure_runtime_ready, get_workspace, get_workspace_status, run_in_workspace

_REMOTE_REPO_PATH = "/home/coder/posthog"
_REMOTE_GIT_TIMEOUT_SECONDS = 120
_DETACHED = "HEAD"

_PROBE_BOX_HEAD_SCRIPT = f"""
cd {_REMOTE_REPO_PATH} || exit 1
git symbolic-ref --quiet --short HEAD || echo {_DETACHED}
git rev-parse HEAD
git status --porcelain --untracked-files=no | head -n 1 | wc -l
"""

# Exit codes of the checkout script, read by _align_box_checkout.
_CHECKOUT_DIRTY = 3
_CHECKOUT_SHA_UNAVAILABLE = 2
_CHECKOUT_BRANCH_DIVERGED = 4
_CHECKOUT_DETACHED_UNSAVED = 5

# The dirty check repeats inside the script so that an edit made on the box
# after the probe still blocks the checkout. `checkout -B` only runs when the
# box's branch is an ancestor of the target, and a detached HEAD is left only
# when a ref or the target still reaches it, so box-only commits are never
# dropped. `--no-overwrite-ignore` keeps ignored files such as `.env.local`.
# Hooks stay off for every git call, fetches included, because the box's branch
# may carry an untrusted hook, and the session forwards the user's SSH agent.
_CHECKOUT_SCRIPT = f"""
branch="$1"; sha="$2"
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null
cd {_REMOTE_REPO_PATH} || exit 1
[ -z "$(git status --porcelain --untracked-files=no)" ] || exit {_CHECKOUT_DIRTY}
has_sha() {{ git cat-file -e "$sha^{{commit}}" 2>/dev/null; }}
has_sha || [ "$branch" = {_DETACHED} ] || git fetch --quiet origin "$branch" 2>/dev/null || true
has_sha || git fetch --quiet origin "$sha" 2>/dev/null || true
has_sha || exit {_CHECKOUT_SHA_UNAVAILABLE}
if ! git symbolic-ref --quiet HEAD >/dev/null \\
    && ! git merge-base --is-ancestor HEAD "$sha" \\
    && [ -z "$(git for-each-ref --contains HEAD --count=1)" ]; then
    exit {_CHECKOUT_DETACHED_UNSAVED}
fi
[ "$branch" = {_DETACHED} ] && exec git checkout --quiet --no-overwrite-ignore --detach "$sha"
if git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null \\
    && ! git merge-base --is-ancestor "refs/heads/$branch" "$sha"; then
    exit {_CHECKOUT_BRANCH_DIVERGED}
fi
exec git checkout --quiet --no-overwrite-ignore -B "$branch" "$sha"
"""


@dataclass(frozen=True)
class GitHead:
    branch: str
    sha: str

    def describe(self) -> str:
        where = "a detached HEAD" if self.branch == _DETACHED else f"`{self.branch}`"
        return f"{where} at {self.sha[:10]}"


@dataclass(frozen=True)
class BoxGitState:
    head: GitHead
    dirty: bool


class BoxCheckoutAction(Enum):
    SKIP = "skip"
    MATCHES = "matches"
    CHECKOUT = "checkout"
    WARN_DIRTY = "warn_dirty"
    FAIL_DIRTY = "fail_dirty"


def decide_box_checkout(local: GitHead, box: BoxGitState, requested: bool | None) -> BoxCheckoutAction:
    """Decide whether to move the box's checkout to the local branch before the first mirror.

    ``requested`` is the ``--checkout-branch`` flag: ``None`` checks out only
    on a clean box, ``True`` fails on a dirty one, ``False`` never touches it.
    """
    if requested is False:
        return BoxCheckoutAction.SKIP
    same_branch = local.branch == box.head.branch or local.branch == _DETACHED
    if local.sha == box.head.sha and same_branch:
        return BoxCheckoutAction.MATCHES
    if box.dirty:
        return BoxCheckoutAction.FAIL_DIRTY if requested else BoxCheckoutAction.WARN_DIRTY
    return BoxCheckoutAction.CHECKOUT


def _detect_local_posthog_checkout() -> Path:
    """Find the local PostHog checkout root by walking up from cwd.

    A checkout is identified by a co-located ``hogli.yaml`` and ``.git``
    directory at the same level. Bails with a hint if we can't find one --
    running ``hogli devbox:sync`` from anywhere outside the repo is almost
    certainly a mistake.
    """
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "hogli.yaml").is_file() and (candidate / ".git").exists():
            return candidate
    _fail(
        "Could not find a PostHog checkout above the current directory.\n"
        "Run `hogli devbox:sync` from inside a `posthog` clone."
    )
    raise SystemExit(1)  # unreachable; helps the type checker see no fall-through


def _read_local_head(local_path: Path) -> GitHead | None:
    result = subprocess.run(
        ["git", "-C", str(local_path), "rev-parse", "HEAD", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    lines = result.stdout.split()
    if result.returncode != 0 or len(lines) != 2:
        return None
    return GitHead(branch=lines[1], sha=lines[0])


def _run_box_script(workspace: str, script: str, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return run_in_workspace(
            workspace, ["bash", "-c", script, "hogli-sync", *args], timeout=_REMOTE_GIT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return None


def _probe_box_state(workspace: str) -> BoxGitState | None:
    result = _run_box_script(workspace, _PROBE_BOX_HEAD_SCRIPT)
    if result is None or result.returncode != 0:
        return None
    lines = result.stdout.split()
    if len(lines) != 3:
        return None
    return BoxGitState(head=GitHead(branch=lines[0], sha=lines[1]), dirty=lines[2] != "0")


def _align_box_checkout(workspace: str, local_path: Path, requested: bool | None) -> None:
    """Put the box on the local branch and commit before the first mirror is created.

    A one-way-safe mirror has no common ancestor on its first scan, so every
    tracked file that differs between the two checkouts becomes a conflict.
    Matching the box's HEAD to the local HEAD first leaves only local
    uncommitted edits to differ. Any failure here falls back to the previous
    behavior (mirror over the box's current checkout) unless the user passed
    ``--checkout-branch``.
    """
    if requested is False:
        return

    def give_up(message: str) -> None:
        if requested:
            _fail(f"{message}\nRun without --checkout-branch to sync anyway.")
        click.echo(click.style(f"{message}\nFiles that differ will show as sync conflicts.", fg="yellow"))

    local = _read_local_head(local_path)
    if local is None:
        give_up("Couldn't read the local branch, so the devbox checkout was left as is.")
        return
    box = _probe_box_state(workspace)
    if box is None:
        give_up("Couldn't read the devbox's git state, so its checkout was left as is.")
        return

    action = decide_box_checkout(local, box, requested)
    if action is BoxCheckoutAction.MATCHES:
        return
    if action in (BoxCheckoutAction.WARN_DIRTY, BoxCheckoutAction.FAIL_DIRTY):
        give_up(
            f"The devbox has uncommitted changes on {box.head.describe()}, so hogli didn't switch it to "
            f"{local.describe()}. Commit or discard them on the devbox before the next sync to let hogli switch it."
        )
        return

    click.echo(f"Devbox is on {box.head.describe()}. Checking out {local.describe()} there first...")
    result = _run_box_script(workspace, _CHECKOUT_SCRIPT, local.branch, local.sha)
    returncode = None if result is None else result.returncode
    if returncode == 0:
        click.echo("Devbox checkout matches local.")
        return
    if returncode == _CHECKOUT_SHA_UNAVAILABLE:
        give_up(f"The devbox couldn't fetch {local.sha[:10]} from origin. Push the branch to avoid this.")
    elif returncode == _CHECKOUT_BRANCH_DIVERGED:
        give_up(f"The devbox has commits on `{local.branch}` that your local branch doesn't, so hogli left it alone.")
    elif returncode == _CHECKOUT_DETACHED_UNSAVED:
        give_up("The devbox has commits on a detached HEAD that no branch holds, so hogli left it alone.")
    elif returncode == _CHECKOUT_DIRTY:
        give_up("The devbox got uncommitted changes before the checkout, so hogli left it alone.")
    else:
        stderr = "" if result is None else result.stderr.strip()
        give_up(f"Checking out {local.describe()} on the devbox failed. {stderr}".strip())


def _ensure_ssh_config_for_workspace(workspace: str) -> None:
    """Ensure ``ssh coder.{workspace}`` resolves before mutagen tries to dial it.

    We check via ``ssh -G`` (which never connects, just resolves config). If
    the host has no specific entry, mutagen would fail with an opaque SSH
    error; we'd rather tell the user to rerun setup.
    """
    host = f"coder.{workspace}"
    result = subprocess.run(["ssh", "-G", host], capture_output=True, text=True)
    if result.returncode != 0:
        _fail(
            f"SSH config for `{host}` is missing. Run `hogli devbox:setup` to install "
            "Coder workspace entries into your ~/.ssh/config."
        )


def _format_session_status(session: dict[str, Any]) -> str:
    """Render a single mutagen session as a few short lines."""
    name = session.get("name") or session.get("identifier", "?")
    paused = session.get("paused", False)
    status = session.get("status", "")
    alpha = session.get("alpha", {})
    beta = session.get("beta", {})
    alpha_path = alpha.get("path", "?") if isinstance(alpha, dict) else "?"
    beta_path = beta.get("path", "?") if isinstance(beta, dict) else "?"
    state = "paused" if paused else (status or "running")
    lines = [
        f"  {name}",
        f"    state: {state}",
        f"    alpha: {alpha_path}",
        f"    beta:  {beta_path}",
    ]
    # Conflicts are the whole point of one-way-safe: a remote file diverged and
    # mutagen refused to overwrite it. Surface them or the sync looks healthy
    # while the user's edits silently never land. Conflicts are per-path: only
    # the diverged paths are blocked, everything else keeps syncing.
    conflicts = mutagen.conflict_count(session)
    if conflicts:
        lines.append(
            f"    conflicts: {conflicts} (these paths diverged on the remote and won't sync until resolved; other files are unaffected)"
        )
    last_error = session.get("lastError")
    if last_error:
        lines.append(f"    error: {last_error}")
    return "\n".join(lines)


def _print_sessions(sessions: list[dict[str, Any]]) -> None:
    """Print the sync sessions returned by mutagen, one per block."""
    if not sessions:
        click.echo("No active sync sessions.")
        return
    for session in sessions:
        click.echo(_format_session_status(session))


def _session_summary(session: dict[str, Any]) -> dict[str, Any]:
    """Reduce a raw mutagen session to a stable shape for programmatic callers.

    Agents driving the sync loop need to answer "am I synced, and is anything
    conflicting?" without scraping human text. ``conflictPaths`` lists only the
    roots mutagen inlines (capped at 10); ``conflicts`` is the true total, so a
    caller compares ``len(conflictPaths)`` to ``conflicts`` to know it's seeing
    a truncated sample.
    """
    paused = bool(session.get("paused", False))
    status = str(session.get("status", "") or "").strip()
    shown = session.get("conflicts") or []
    alpha = session.get("alpha") if isinstance(session.get("alpha"), dict) else {}
    beta = session.get("beta") if isinstance(session.get("beta"), dict) else {}
    return {
        "name": session.get("name") or session.get("identifier"),
        "state": "paused" if paused else (status or "running"),
        "paused": paused,
        "conflicts": mutagen.conflict_count(session),
        "conflictPaths": [c.get("root") for c in shown if isinstance(c, dict) and c.get("root")],
        "lastError": session.get("lastError"),
        "alpha": alpha.get("path"),
        "beta": beta.get("path"),
    }


@click.command(name="devbox:sync", help="Mirror your local PostHog checkout to a devbox")
@workspace_argument
@click.option("--status", "show_status", is_flag=True, help="Show the current sync state")
@click.option(
    "--json", "as_json", is_flag=True, help="Print sync state as JSON (implies --status; for scripts and agents)"
)
@click.option("--pause", is_flag=True, help="Pause the sync session")
@click.option("--resume", is_flag=True, help="Resume a paused sync session")
@click.option("--terminate", is_flag=True, help="Tear down the sync session")
@click.option("--flush", is_flag=True, help="Force a flush of pending changes")
@click.option(
    "--checkout-branch/--no-checkout-branch",
    "checkout_branch",
    default=None,
    help=(
        "Before creating the sync, check out your local branch and commit on the devbox so the first sync "
        "has no branch conflicts. By default this happens only when the devbox has no uncommitted changes; "
        "--checkout-branch fails instead of skipping, --no-checkout-branch never touches the devbox checkout."
    ),
)
@click.option("-v", "--verbose", is_flag=True, help="Show full install output")
def cmd_sync(
    workspace: str | None,
    show_status: bool,
    as_json: bool,
    pause: bool,
    resume: bool,
    terminate: bool,
    flush: bool,
    checkout_branch: bool | None,
    verbose: bool,
) -> None:
    """Create or manage a one-way-safe mutagen sync session for a devbox.

    Default action is an idempotent create: re-running on a workspace that
    already has a session just prints the status. Use the flag variants to
    operate on an existing session by label.
    """
    chosen = sum([show_status, pause, resume, terminate, flush])
    if chosen > 1:
        raise click.UsageError("Pick at most one of --status, --pause, --resume, --terminate, --flush.")
    if as_json and (pause or resume or terminate or flush):
        raise click.UsageError("--json reports state only; it can't combine with --pause/--resume/--terminate/--flush.")
    if workspace and workspace.startswith("@"):
        # Local is the source of truth: syncing onto another user's box would
        # push your checkout over theirs. v1 targets your own devboxes only.
        _fail("devbox:sync only targets your own devboxes; `@user` shared targets are not supported.")

    name, workspaces = resolve_workspace_name(workspace)
    label = mutagen.workspace_label_selector(name)

    # Lifecycle subcommands don't need the full runtime preflight -- they
    # just talk to the local mutagen daemon. Keep them fast and offline-safe.
    if as_json:
        sessions = mutagen.sync_list(label_selector=label)
        click.echo(json.dumps([_session_summary(s) for s in sessions]))
        return
    if show_status:
        _print_sessions(mutagen.sync_list(label_selector=label))
        return
    if pause:
        mutagen.sync_pause(label)
        click.echo(f"Paused sync for {name}.")
        return
    if resume:
        mutagen.sync_resume(label)
        click.echo(f"Resumed sync for {name}.")
        return
    if terminate:
        mutagen.sync_terminate(label)
        click.echo(f"Terminated sync for {name}.")
        return
    if flush:
        mutagen.sync_flush(label)
        click.echo(f"Flushed sync for {name}.")
        return

    # Default path: idempotent create. Install mutagen and bring the daemon up
    # first so the existing-session check sees sessions persisted across daemon
    # restarts; a re-run then short-circuits before the heavier coder/SSH
    # preflight below. (ensure_runtime_ready covers the coder install check.)
    ensure_sync_session(name, workspaces, None, checkout_branch=checkout_branch, verbose=verbose)


def ensure_sync_session(
    name: str,
    workspaces: list[dict[str, Any]] | None,
    local_path: Path | None,
    *,
    checkout_branch: bool | None = None,
    verbose: bool = False,
) -> None:
    if sync_session_exists(name, verbose=verbose):
        click.echo(
            f"Sync already running for {name}. Use `hogli devbox:sync{_workspace_arg_suffix(name)} --status` to inspect."
        )
        return

    ensure_runtime_ready()
    create_sync_session(name, workspaces, local_path or _detect_local_posthog_checkout(), checkout_branch)
    click.echo("Sync created. Initial scan and copy may take a few minutes for large checkouts.")
    click.echo(f"Inspect: hogli devbox:sync{_workspace_arg_suffix(name)} --status")


def sync_session_exists(name: str, *, verbose: bool = False) -> bool:
    mutagen.ensure_mutagen_installed(verbose=verbose)
    mutagen.ensure_daemon_with_shim()
    return bool(mutagen.sync_list(label_selector=mutagen.workspace_label_selector(name)))


def create_sync_session(
    name: str, workspaces: list[dict[str, Any]] | None, local_path: Path, checkout_branch: bool | None = None
) -> None:
    _ensure_workspace_running(name, workspaces)
    _ensure_ssh_config_for_workspace(name)
    config_path = mutagen.ensure_user_mutagen_config()

    _align_box_checkout(name, local_path, checkout_branch)
    click.echo(f"Creating sync: {local_path} -> coder.{name}:{_REMOTE_REPO_PATH}")
    mutagen.sync_create(
        name=f"ph-{name}",
        src=str(local_path),
        dst=f"coder.{name}:{_REMOTE_REPO_PATH}",
        config_path=config_path,
        labels=mutagen.workspace_labels(name),
    )


def _ensure_workspace_running(name: str, workspaces: list[dict[str, Any]] | None) -> None:
    """Fail early with a clear message if the target devbox isn't running.

    mutagen dials the box over SSH; a stopped box otherwise surfaces as an
    opaque connection error partway through the sync. Best-effort: when the
    workspace list is unavailable (e.g. a shared ``@user`` target) we skip the
    check rather than block on an unknowable state.
    """
    if not workspaces:
        return
    workspace = get_workspace(name, workspaces)
    if workspace is None:
        return
    status = get_workspace_status(workspace)
    if status != "running":
        _fail(f"Devbox '{name}' is {status}, not running. Run `hogli devbox:start` first.")
