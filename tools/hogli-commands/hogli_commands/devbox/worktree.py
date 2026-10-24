"""`hogli devbox:worktree` gives a local git worktree its own labeled devbox and sync mirror."""

from __future__ import annotations

import re
import hashlib
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from . import mutagen
from .cli import _preferred_region, devbox_clone, devbox_start, resolve_workspace_name
from .coder import (
    REGION_NAME_SUFFIXES,
    _fail,
    ensure_runtime_ready,
    extract_workspace_label,
    get_coder_url,
    get_username,
    get_workspace,
    get_workspace_name,
    get_workspace_status,
    list_user_workspaces,
    region_from_workspace_name,
)
from .config import (
    WORKTREE_BOX_CLEANUP_ACTIONS,
    clear_worktree_box_cleanup,
    load_worktree_boxes,
    record_worktree_box,
    save_worktree_box_cleanup,
)
from .sync import _REMOTE_REPO_PATH, _detect_local_posthog_checkout, ensure_sync_session

CODER_NAME_MAX_LENGTH = 32
_HASH_LENGTH = 4
_BRANCH_PREFIXES_TO_DROP = ("worktree-",)
_RESERVED_SUFFIXES = tuple(suffix for suffix in REGION_NAME_SUFFIXES.values() if suffix)


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
    rename, so a re-run never creates a second box.
    """
    registered = load_worktree_boxes().get(str(root))
    registered_label = extract_workspace_label(registered) if registered is not None else None
    if registered is not None and registered_label is not None and label in (None, registered_label):
        return _WorktreeTarget(workspace_name=registered, label=registered_label)

    if cloning:
        region = region_from_workspace_name(resolve_workspace_name(clone_source)[0])
    else:
        region = _preferred_region()

    resolved_label = label or derive_label(_current_branch(root), label_budget(get_username(), region))
    name = get_workspace_name(resolved_label, region=region)
    if len(name) > CODER_NAME_MAX_LENGTH:
        _fail(f"'{name}' is longer than Coder's {CODER_NAME_MAX_LENGTH}-character limit. Pick a shorter `--label`.")

    if registered is not None and registered != name and get_workspace(registered, workspaces) is not None:
        _fail(
            f"This worktree already has devbox '{registered}'. Remove it with "
            f"`hogli devbox:destroy {registered_label or ''}` before you pick another label."
        )
    if label is None and registered != name and get_workspace(name, workspaces) is not None:
        _fail(
            f"A devbox named '{name}' already exists and is not tied to this worktree. "
            f"Pass `--label {resolved_label}` to use it anyway, or `--label <other>` for a new box."
        )
    return _WorktreeTarget(workspace_name=name, label=resolved_label)


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
    dry_run: bool,
    yes: bool,
    verbose: bool,
) -> None:
    root = _detect_local_posthog_checkout()
    if not _is_linked_worktree(root):
        _fail(
            f"{root} is the main checkout, not a linked worktree. "
            "Use `hogli devbox:start` and `hogli devbox:sync` for it."
        )

    ensure_runtime_ready()
    workspaces = list_user_workspaces()
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

    record_worktree_box(root, target.workspace_name)
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

    ensure_sync_session(target.workspace_name, list_user_workspaces(), root, verbose=verbose)
    click.echo()
    click.echo(f"App URL, once the stack runs on the box: {_app_url(target.workspace_name)}")
