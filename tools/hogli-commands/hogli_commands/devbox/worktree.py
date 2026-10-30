"""`hogli devbox:worktree` gives a local git worktree its own labeled devbox and sync mirror."""

from __future__ import annotations

import re
import sys
import hashlib
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from ..worktrees import worktree_source
from . import mutagen
from .cli import _preferred_region, devbox_clone, devbox_start, resolve_workspace_name
from .coder import (
    REGION_NAME_SUFFIXES,
    _fail,
    ensure_runtime_ready,
    extract_workspace_label,
    fetch_user_workspaces,
    get_coder_url,
    get_username,
    get_workspace,
    get_workspace_name,
    get_workspace_status,
    region_from_workspace_name,
)
from .config import (
    WORKTREE_AUTO_SOURCES,
    WORKTREE_BOX_CLEANUP_ACTIONS,
    WorktreeBoxRecord,
    claim_worktree_box,
    clear_worktree_auto_sources,
    clear_worktree_box_cleanup,
    ensure_worktree_id,
    load_worktree_boxes,
    record_worktree_box,
    save_worktree_auto_sources,
    save_worktree_box_cleanup,
    saved_worktree_auto_sources,
    worktree_box_claimant,
)
from .sync import _REMOTE_REPO_PATH, _detect_local_posthog_checkout, ensure_sync_session

CODER_NAME_MAX_LENGTH = 32
_HASH_LENGTH = 4
_BRANCH_PREFIXES_TO_DROP = ("worktree-",)
_RESERVED_SUFFIXES = tuple(suffix for suffix in REGION_NAME_SUFFIXES.values() if suffix)
_AUTO_OFF = "off"
_AUTO_LOG_NAME = "hogli-devbox-worktree.log"
_SUBAGENT_WORKTREE_PREFIX = "agent-"


def label_budget(username: str, region: str) -> int:
    region_suffix = REGION_NAME_SUFFIXES.get(region, "")
    used = len(f"devbox-{username}-") + (len(region_suffix) + 1 if region_suffix else 0)
    return CODER_NAME_MAX_LENGTH - used


def derive_label(branch: str, max_length: int) -> str:
    """Turn a branch name into a devbox label that fits Coder's 32-character workspace name limit.

    A label that had to be shortened or repaired gets a hash of the full branch
    name, so two long branches with a shared prefix still map to different boxes.
    """
    if max_length < _HASH_LENGTH:
        _fail(
            f"Your Coder username leaves room for only {max(max_length, 0)} label characters. "
            "Pass `--label <label>` with a short label instead."
        )
    slug = branch.lower()
    for prefix in _BRANCH_PREFIXES_TO_DROP:
        if slug.startswith(prefix) and len(slug) > len(prefix):
            slug = slug[len(prefix) :]
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    reserved = any(slug == suffix or slug.endswith(f"-{suffix}") for suffix in _RESERVED_SUFFIXES)
    if slug and len(slug) <= max_length and not reserved:
        return slug

    digest = hashlib.sha256(branch.encode()).hexdigest()[:_HASH_LENGTH]
    stem_length = max_length - _HASH_LENGTH - 1
    stem = slug[:stem_length].rstrip("-") if stem_length > 0 else ""
    return f"{stem}-{digest}" if stem else digest


def _is_linked_worktree(root: Path) -> bool:
    return (root / ".git").is_file()


def _current_branch(root: Path) -> str:
    result = subprocess.run(["git", "symbolic-ref", "--short", "-q", "HEAD"], cwd=root, capture_output=True, text=True)
    branch = result.stdout.strip() if result.returncode == 0 else ""
    return branch or root.name


def parse_auto_sources(value: str) -> tuple[str, ...]:
    if value.strip() == _AUTO_OFF:
        return ()
    sources = tuple(dict.fromkeys(source.strip() for source in value.split(",") if source.strip()))
    unknown = [source for source in sources if source not in WORKTREE_AUTO_SOURCES]
    if unknown or not sources:
        raise click.BadParameter(
            f"Use a comma-separated list of {', '.join(WORKTREE_AUTO_SOURCES)}, or '{_AUTO_OFF}'.",
            param_hint="--auto",
        )
    return sources


def should_auto_provision(root: Path, source: str, enabled: frozenset[str]) -> bool:
    # A Claude subagent worktree lives for one task, and a fan-out would create one box per agent.
    if source == "claude" and root.name.startswith(_SUBAGENT_WORKTREE_PREFIX):
        return False
    return source in enabled


def _save_auto_sources(value: str) -> None:
    sources = parse_auto_sources(value)
    if not sources:
        clear_worktree_auto_sources()
        click.echo("Turned off automatic worktree boxes.")
        return
    save_worktree_auto_sources(sources)
    click.echo(
        f"New worktrees from {', '.join(sources)} now get their own devbox. "
        "The husky post-checkout hook starts `hogli devbox:worktree` in the background when one is created."
    )


def _git_dir(root: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=root, capture_output=True, text=True, check=True
    )
    return Path(result.stdout.strip())


def _app_url(workspace_name: str) -> str:
    host = urllib.parse.urlparse(get_coder_url()).hostname or ""
    return f"https://app--{workspace_name}--{get_username()}.{host}"


@dataclass(frozen=True)
class _WorktreeTarget:
    workspace_name: str
    label: str


def _resolve_target(
    root: Path,
    label: str | None,
    cloning: bool,
    clone_source: str | None,
    workspaces: list[dict[str, Any]],
) -> _WorktreeTarget:
    """Return the devbox this worktree uses.

    A worktree that already has a registered box keeps it, even after a branch
    rename, so a re-run never creates a second box. A record saved for an
    earlier worktree at the same path does not count.
    """
    boxes = load_worktree_boxes()
    registered = boxes.get(str(root))
    if registered is not None and registered.worktree_id is not None and not registered.tracks_worktree(_git_dir(root)):
        registered = None
    registered_box = get_workspace(registered.workspace, workspaces) if registered is not None else None
    if registered is not None and registered_box is not None and not registered.may_adopt(registered_box):
        registered = registered_box = None
    registered_label = extract_workspace_label(registered.workspace) if registered is not None else None
    if registered is not None and registered_label is not None and label in (None, registered_label):
        return _WorktreeTarget(workspace_name=registered.workspace, label=registered_label)

    if cloning:
        region = region_from_workspace_name(resolve_workspace_name(clone_source)[0])
    else:
        region = _preferred_region()

    resolved_label = label or derive_label(_current_branch(root), label_budget(get_username(), region))
    name = get_workspace_name(resolved_label, region=region)
    if len(name) > CODER_NAME_MAX_LENGTH:
        _fail(f"'{name}' is longer than Coder's {CODER_NAME_MAX_LENGTH}-character limit. Pick a shorter `--label`.")

    if registered is not None and registered.workspace != name and registered_box is not None:
        _fail(
            f"This worktree already has devbox '{registered.workspace}'. Remove it with "
            f"`hogli devbox:destroy {registered_label or ''}` before you pick another label."
        )
    existing = get_workspace(name, workspaces)
    owner = worktree_box_claimant(boxes, root, name, existing)
    if owner is not None:
        _fail(f"Devbox '{name}' belongs to the worktree at {owner}. Pick another `--label`.")
    if label is None and registered is None and existing is not None:
        _fail(
            f"A devbox named '{name}' already exists and is not tied to this worktree. "
            f"Pass `--label {resolved_label}` to use it anyway, or `--label <other>` for a new box."
        )
    return _WorktreeTarget(workspace_name=name, label=resolved_label)


def _list_workspaces_or_fail() -> list[dict[str, Any]]:
    workspaces = fetch_user_workspaces()
    if workspaces is None:
        _fail(
            "Couldn't list your devboxes, so hogli can't tell which one belongs to this worktree. "
            "Run `hogli devbox:doctor`."
        )
        raise SystemExit(1)  # unreachable; helps the type checker see no fall-through
    return workspaces


@click.command(name="devbox:worktree", help="Give this worktree its own devbox and sync mirror")
@click.option("--label", default=None, help="Devbox label to use instead of one derived from the branch name")
@click.option(
    "--clone-from",
    default=None,
    metavar="LABEL",
    help="Create the box as a clone of this running devbox (see devbox:clone). Use 'default' for your default box.",
)
@click.option(
    "--start-app/--no-start-app",
    "start_app",
    default=None,
    help="Bring the PostHog app up on every start. Applies only when the box is created.",
)
@click.option(
    "--on-clean",
    type=click.Choice([*WORKTREE_BOX_CLEANUP_ACTIONS, "keep"]),
    default=None,
    help="Save what `hogli worktrees:clean` does with a worktree's devbox when it removes the worktree.",
)
@click.option(
    "--auto",
    "auto_sources",
    default=None,
    metavar="SOURCES",
    help=(
        "Save which new worktrees get a devbox automatically, as a comma-separated list of "
        f"{', '.join(WORKTREE_AUTO_SOURCES)}. 'off' turns it off. Only saves the setting."
    ),
)
@click.option("--dry-run", is_flag=True, help="Print the plan without changing anything")
@click.option("-y", "--yes", is_flag=True, help="Skip the clone confirmation prompt")
@click.option("-v", "--verbose", is_flag=True, help="Show full Coder/Terraform build output")
@click.pass_context
def devbox_worktree(
    ctx: click.Context,
    label: str | None,
    clone_from: str | None,
    start_app: bool | None,
    on_clean: str | None,
    auto_sources: str | None,
    dry_run: bool,
    yes: bool,
    verbose: bool,
) -> None:
    if auto_sources is not None:
        _save_auto_sources(auto_sources)
        return

    root = _detect_local_posthog_checkout()
    if not _is_linked_worktree(root):
        _fail(
            f"{root} is the main checkout, not a linked worktree. "
            "Use `hogli devbox:start` and `hogli devbox:sync` for it."
        )

    ensure_runtime_ready()
    workspaces = _list_workspaces_or_fail()
    cloning = clone_from is not None
    clone_source = None if clone_from in (None, "default") else clone_from
    target = _resolve_target(root, label, cloning, clone_source, workspaces)
    existing = get_workspace(target.workspace_name, workspaces)
    has_sync = bool(mutagen.sync_list(label_selector=mutagen.workspace_label_selector(target.workspace_name)))

    if existing is None:
        box_step = (
            f"Clone '{clone_from}' into '{target.workspace_name}'" if cloning else f"Create '{target.workspace_name}'"
        )
    elif get_workspace_status(existing) == "running":
        box_step = f"Use running devbox '{target.workspace_name}'"
    else:
        box_step = f"Start devbox '{target.workspace_name}' ({get_workspace_status(existing)})"
    sync_step = (
        "Keep the existing sync mirror"
        if has_sync
        else f"Mirror {root} to coder.{target.workspace_name}:{_REMOTE_REPO_PATH}"
    )

    click.echo(f"Worktree: {root}")
    click.echo(f"  1. {box_step}")
    click.echo(f"  2. {sync_step}")
    if on_clean is not None:
        click.echo(f"  3. Save worktrees:clean devbox action: {on_clean}")
    if dry_run:
        click.echo("[DRY-RUN] Nothing changed.")
        return

    git_dir = _git_dir(root)
    worktree_id = ensure_worktree_id(git_dir)
    owner = claim_worktree_box(
        root,
        WorktreeBoxRecord(
            workspace=target.workspace_name,
            git_dir=str(git_dir),
            workspace_id=None if existing is None else existing.get("id"),
            worktree_id=worktree_id,
        ),
        existing,
    )
    if owner is not None:
        _fail(f"Devbox '{target.workspace_name}' belongs to the worktree at {owner}. Pick another `--label`.")
    if on_clean == "keep":
        clear_worktree_box_cleanup()
    elif on_clean is not None:
        save_worktree_box_cleanup(on_clean)

    region = region_from_workspace_name(target.workspace_name)
    if existing is None and cloning:
        ctx.invoke(devbox_clone, workspace=clone_source, new_label=target.label, yes=yes, verbose=verbose)
    elif existing is None:
        ctx.invoke(devbox_start, workspace=target.label, region=region, start_app=start_app, verbose=verbose)
    else:
        ctx.invoke(devbox_start, workspace=target.label, region=region, verbose=verbose)

    workspaces = _list_workspaces_or_fail()
    created = get_workspace(target.workspace_name, workspaces)
    if existing is None and created is not None:
        record_worktree_box(
            root,
            WorktreeBoxRecord(
                workspace=target.workspace_name,
                git_dir=str(git_dir),
                workspace_id=created.get("id"),
                worktree_id=worktree_id,
            ),
        )
    ensure_sync_session(target.workspace_name, workspaces, root, verbose=verbose)
    click.echo()
    click.echo(f"App URL, once the stack runs on the box: {_app_url(target.workspace_name)}")


@click.command(
    name="devbox:worktree:auto",
    help="Start devbox:worktree in the background for this new worktree, if `devbox:worktree --auto` covers it",
)
def devbox_worktree_auto() -> None:
    enabled = saved_worktree_auto_sources()
    if not enabled:
        return
    root = _detect_local_posthog_checkout()
    if not _is_linked_worktree(root) or not should_auto_provision(root, worktree_source(root), enabled):
        return

    log_path = _git_dir(root) / _AUTO_LOG_NAME
    with log_path.open("ab") as log:
        subprocess.Popen(
            # -P keeps the worktree off sys.path, so a `hogli` package committed to the
            # branch being checked out cannot shadow the installed one and run here.
            [sys.executable, "-P", "-m", "hogli", "devbox:worktree", "--yes"],
            cwd=root,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    click.echo(f"hogli: creating a devbox for this worktree in the background. Log: {log_path}")
