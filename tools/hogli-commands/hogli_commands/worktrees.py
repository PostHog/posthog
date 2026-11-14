"""Clean up unused agent and phw worktrees (Claude Code, Codex, PostHog Desktop, phw).

These tools each create throwaway git worktrees that accumulate over time. A
single PostHog worktree carries multi-GB `node_modules`, Python venvs, and Rust
build artifacts, so stale ones are by far the largest reclaimable disk on a dev
machine. This command finds them, filters by age, and either removes the whole
worktree or just its dependencies and build output (keeping the code).

The discovery roots and dependency patterns are PostHog-specific, but the age
logic and deletion modes are generic.

Safety: age is a staleness heuristic, not a "no unsaved work" guarantee — edits
made without any git operation may not move the activity signal. So `--mode full`
skips a worktree with uncommitted/untracked changes, unpushed commits, or git
state it cannot read (present-but-corrupt/locked) unless `--include-dirty` is
given. Unpushed commits whose work a squash merge landed on the default branch
do not count, because the merge queue rewrites every pull request that way. Orphaned worktrees (admin gitdir pruned) are removed by default: deleting
the directory never touches git refs, so committed work survives in the shared
repo — only uncommitted edits in an already-stale tree could be lost. `--mode
deps` and `--mode build` only remove recreatable artifacts, so they have no such
gate, so they can strip a worktree that is idle by the activity signal but still
has a live dev server running. They never remove a path that holds a tracked
file, and `build` removes only paths that git ignores. Every mode skips a
worktree where cargo or rustc runs, and deps and build keep a Cargo target that
a build used after the cutoff.
"""

from __future__ import annotations

import os
import re
import sys
import stat
import time
import fcntl
import shutil
import itertools
import subprocess
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

import click
from hogli import telemetry
from hogli.manifest import REPO_ROOT

from .cargo_targets import (
    last_cargo_build_epoch,
    looks_like_cargo_target,
    unused_legacy_cargo_target,
    worktrees_running_cargo,
)
from .devbox import herdr, hogland, mutagen
from .devbox.coder import (
    delete_workspace,
    ensure_runtime_ready,
    extract_workspace_label,
    fetch_user_workspaces,
    get_workspace,
    get_workspace_status,
    stop_workspace,
)
from .devbox.config import (
    WorktreeBoxRecord,
    forget_worktree_boxes,
    load_worktree_boxes,
    read_worktree_id,
    saved_worktree_box_cleanup,
    worktree_prune_lock,
)
from .disk_usage import NO_USAGE, DiskUsage, measure_disk_usage
from .doctor import _format_size

WORKTREE_SOURCES = ("claude", "claude-scratchpad", "codex", "posthog-code", "phw", "other")


# Roots that hold agent-created worktrees, keyed by the tool that owns them.
# Claude Code nests worktrees under the repo. The Codex app and PostHog Desktop
# keep them in the home directory as <id>/<repo>, and Claude Code agents make
# throwaway ones in their scratchpad. Returned as (source, root). The phw root
# must match WORKTREE_BASE in bin/posthog-worktree, including its
# POSTHOG_WORKTREE_BASE override.
def _worktree_roots(repo_root: Path) -> list[tuple[str, Path]]:
    phw_base = os.environ.get("POSTHOG_WORKTREE_BASE") or str(Path.home() / ".worktrees" / "posthog")
    scratchpad_root = _claude_scratchpad_root()
    return [
        ("claude", repo_root / ".claude" / "worktrees"),
        *([("claude-scratchpad", scratchpad_root)] if scratchpad_root is not None else []),
        ("codex", repo_root / ".codex" / "worktrees"),
        ("codex", repo_root / ".codex-worktrees"),
        ("codex", Path.home() / ".codex" / "worktrees"),
        ("posthog-code", Path.home() / ".posthog-code" / "worktrees"),
        ("phw", Path(phw_base).expanduser()),
    ]


def _claude_scratchpad_root(shared_tmp: Path = Path("/tmp")) -> Path | None:
    """The scratchpad root, or None unless it is a real folder that only this user owns and can write to.

    /tmp is shared, so another user can create this name first, or make it a
    symlink that points discovery at someone else's folders.
    """

    root = shared_tmp / f"claude-{os.getuid()}"
    try:
        status = root.lstat()
    except OSError:
        return None
    if not stat.S_ISDIR(status.st_mode) or status.st_uid != os.getuid() or status.st_mode & 0o022:
        return None
    return root


# Claude Code's scratchpad worktrees sit at <root>/<encoded project>/<session id>/scratchpad/<worktree>.
_SCRATCHPAD_DISCOVERY_DEPTH = 4


def worktree_source(path: Path) -> str:
    """Name the tool whose worktree root holds *path*, or ``other`` for a worktree made elsewhere."""
    return _source_under(_resolve(path), _resolve_repo(str(path)))


def _source_under(resolved_path: Path, repo_root: Path) -> str:
    for source, root in _worktree_roots(repo_root):
        if _is_under(resolved_path, root):
            return source
    return "other"


ARTIFACT_KINDS = ("deps", "build")
_DEPS = frozenset({"deps"})
_BUILD = frozenset({"build"})


def _is_python_venv(path: Path) -> bool:
    return (path / "pyvenv.cfg").is_file()


_BUILD_MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml", "go.mod", "CMakeLists.txt")


def _beside_build_manifest(path: Path) -> bool:
    return any((path.parent / manifest).is_file() for manifest in _BUILD_MANIFESTS)


@dataclass(frozen=True, kw_only=True, slots=True)
class _ArtifactRule:
    kinds: frozenset[str]
    applies_to: Callable[[Path], bool] = lambda path: True


ARTIFACT_DIRS: dict[str, _ArtifactRule] = {
    "node_modules": _ArtifactRule(kinds=_DEPS),
    ".venv": _ArtifactRule(kinds=_DEPS, applies_to=_is_python_venv),
    "venv": _ArtifactRule(kinds=_DEPS, applies_to=_is_python_venv),
    ".tox": _ArtifactRule(kinds=_DEPS),
    ".nox": _ArtifactRule(kinds=_DEPS),
    ".pnpm-store": _ArtifactRule(kinds=_DEPS),
    # Cargo builds the dependencies and the repo's own crates into the same target dir.
    "target": _ArtifactRule(kinds=_DEPS | _BUILD, applies_to=looks_like_cargo_target),
    "__pycache__": _ArtifactRule(kinds=_BUILD),
    ".pytest_cache": _ArtifactRule(kinds=_BUILD),
    ".mypy_cache": _ArtifactRule(kinds=_BUILD),
    ".ruff_cache": _ArtifactRule(kinds=_BUILD),
    ".parcel-cache": _ArtifactRule(kinds=_BUILD),
    ".turbo": _ArtifactRule(kinds=_BUILD),
    ".next": _ArtifactRule(kinds=_BUILD),
    ".nuxt": _ArtifactRule(kinds=_BUILD),
    ".svelte-kit": _ArtifactRule(kinds=_BUILD),
    ".vite": _ArtifactRule(kinds=_BUILD),
    ".react-router": _ArtifactRule(kinds=_BUILD),
    "storybook-static": _ArtifactRule(kinds=_BUILD),
    "playwright-report": _ArtifactRule(kinds=_BUILD),
    "test-results": _ArtifactRule(kinds=_BUILD),
    "blob-report": _ArtifactRule(kinds=_BUILD),
    "htmlcov": _ArtifactRule(kinds=_BUILD),
    # These names are generic, so they count only as the output of a package built in the same directory.
    "coverage": _ArtifactRule(kinds=_BUILD, applies_to=_beside_build_manifest),
    "dist": _ArtifactRule(kinds=_BUILD, applies_to=_beside_build_manifest),
    "build": _ArtifactRule(kinds=_BUILD, applies_to=_beside_build_manifest),
}

# Flox keeps environment state such as a local Postgres data dir under .flox/cache, so only these children are artifacts.
FLOX_CACHE_ARTIFACTS: dict[str, frozenset[str]] = {"venv": _DEPS, "go": _DEPS, "go-build": _BUILD}

# A .tsbuildinfo left behind makes `tsc --build` skip emitting into an outDir that was removed.
BUILD_FILE_SUFFIXES = (".tsbuildinfo", ".node")

BUILD_EXPLICIT_PATHS = ("frontend/.cache", "frontend/tmp")

_WALK_SKIP = frozenset({".git", ".venv", "venv"})

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


@dataclass(frozen=True, kw_only=True, slots=True)
class _ReapResult:
    reclaimed_bytes: float
    removed: int
    failed: int


@dataclass
class Worktree:
    """A discovered agent worktree."""

    source: str
    path: Path
    registered: bool
    locked: bool
    branch: str
    last_activity: float
    usage: DiskUsage = NO_USAGE
    artifact_items: list[Path] = field(default_factory=list)
    dirty: bool = False
    unpushed: int = 0
    squash_merged: str | None = None
    detached: bool = False
    state_unknown: bool = False

    @property
    def unsafe(self) -> bool:
        """Holds (or might hold) work that a full removal would destroy.

        Includes worktrees whose git state we couldn't read — an orphaned or
        unreadable worktree might contain uncommitted work, so we fail closed
        and treat "can't verify it's clean" as unsafe rather than deleting it.
        Unpushed commits that a squash merge landed are not work at risk.
        """
        return self.dirty or (self.unpushed > 0 and self.squash_merged is None) or self.state_unknown


@dataclass(frozen=True)
class WorktreeBox:
    """A registered devbox paired with the worktree it was set up for.

    ``worktree_path`` is the registry key, which `git worktree move` leaves
    behind. ``current_path`` carries where the checkout is now, so a move does
    not hide the box from cleanup or strand its registry entry.
    """

    worktree_path: Path
    record: WorktreeBoxRecord
    current_path: Path | None = None

    @property
    def workspace(self) -> str:
        return self.record.workspace

    @property
    def checkout_path(self) -> Path:
        return self.current_path or self.worktree_path


@click.command(
    name="worktrees:clean",
    help="Clear out unused Claude Code / Codex / PostHog Desktop / phw worktrees by age",
)
@click.option(
    "--before",
    default=None,
    metavar="DATE|INTERVAL|all",
    help="Required. Cutoff: a date (2026-06-01), a relative age like 7d/2w "
    "(matches worktrees idle longer than that), or 'all' for everything.",
)
@click.option(
    "--mode",
    default=None,
    metavar="full|deps|build",
    help="Required. 'full' removes the whole worktree. 'deps' removes installed dependencies such as node_modules, "
    "Python venvs and Cargo target dirs. 'build' removes build output and tool caches that git ignores, such as "
    "Cargo target, dist, .next and __pycache__. Combine deps and build with a comma: --mode deps,build.",
)
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=click.Choice(WORKTREE_SOURCES, case_sensitive=False),
    help="Restrict to specific tool(s). Repeatable. 'other' is a worktree that `git worktree list` registers "
    "outside every tool's folder. Default: all of them, except that --mode full skips 'other' unless you name it.",
)
@click.option(
    "--repo",
    default=None,
    metavar="PATH",
    help="Repository whose worktrees to clean. Defaults to the current repo. "
    "Lets you reuse this on repos that don't ship hogli.",
)
@click.option(
    "--include-dirty",
    is_flag=True,
    help="In --mode full, also remove worktrees with uncommitted/unpushed work or "
    "unreadable git state. Default: skip them. (Orphaned worktrees are governed by --orphans.)",
)
@click.option(
    "--orphans",
    type=click.Choice(["yes", "no", "ask"], case_sensitive=False),
    default=None,
    help="What to do with orphaned worktrees (admin entry pruned, not in `git worktree list`; "
    "committed work is safe in branch refs). yes=include, no=skip, ask=prompt when any are found. "
    "Default: yes for --mode deps and build, ask for --mode full. deps and build still remove nothing from an "
    "orphan, because git cannot check what its branch tracks.",
)
@click.option(
    "--stop-boxes",
    is_flag=True,
    help="In --mode full, also stop the devbox that `hogli devbox:worktree` set up for each removed worktree.",
)
@click.option(
    "--delete-boxes",
    is_flag=True,
    help="In --mode full, also delete the devbox that `hogli devbox:worktree` set up for each removed worktree, "
    "including its disk.",
)
@click.option(
    "--keep-boxes",
    is_flag=True,
    help="Leave devboxes alone, overriding the action saved with `hogli devbox:worktree --on-clean`.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.option(
    "--unattended",
    is_flag=True,
    help="For a scheduler: once a day, remove worktrees idle for 14 days, then strip deps and build output from worktrees "
    "idle for 7 days. Implies --yes and --keep-boxes.",
)
@click.option("--skip-hand-made", is_flag=True, hidden=True)
@click.pass_context
def worktrees_clean(
    ctx: click.Context,
    before: str | None,
    mode: str | None,
    sources: tuple[str, ...],
    repo: str | None,
    include_dirty: bool,
    orphans: str | None,
    stop_boxes: bool,
    delete_boxes: bool,
    keep_boxes: bool,
    dry_run: bool,
    yes: bool,
    unattended: bool,
    skip_hand_made: bool = False,
) -> None:
    """Find and clean up stale agent worktrees by age and deletion mode."""

    if unattended:
        if before is not None or mode is not None or include_dirty or stop_boxes or delete_boxes:
            raise click.UsageError(
                "--unattended cannot be combined with --before, --mode, --include-dirty, --stop-boxes or --delete-boxes."
            )
        lock = _unattended_lock(dry_run)
        if lock is None:
            click.echo("Skipped: an unattended run is in progress or happened in the last 24 hours.")
            return
        for age, tier in _UNATTENDED_SCHEDULE:
            click.echo(f"--- {datetime.now():%Y-%m-%d %H:%M} --mode {tier} --before {age}")
            # A saved `--on-clean delete` default must not delete devboxes from a
            # background run that nobody watches.
            ctx.invoke(
                worktrees_clean,
                before=age,
                mode=tier,
                repo=repo,
                sources=sources,
                # A worktree outside every tool folder is often a long-lived checkout that a person made by hand.
                skip_hand_made=True,
                orphans=orphans,
                dry_run=dry_run,
                yes=True,
                keep_boxes=True,
            )
        return

    # Both selectors are mandatory — without an explicit age cutoff and mode we
    # do nothing, so an accidental bare invocation can never delete anything.
    # UsageError (exit 2) so a scripted caller can detect the misuse.
    if before is None or mode is None:
        raise click.UsageError(
            "Both --before and --mode are required.\n\n"
            "Examples:\n"
            "  hogli worktrees:clean --before 7d --mode deps     # free deps in worktrees idle >7 days\n"
            "  hogli worktrees:clean --before 7d --mode deps,build\n"
            "  hogli worktrees:clean --before 2026-06-01 --mode full\n"
            "  hogli worktrees:clean --before all --mode full --dry-run\n"
            "  hogli worktrees:clean --before 30d --mode full --repo ~/Projects/other-repo"
        )

    mode = _parse_mode(mode)
    box_action = _resolve_box_action(stop_boxes, delete_boxes, keep_boxes, mode)
    orphan_policy = _resolve_orphan_policy(orphans, mode)
    repo_root = _resolve_repo(repo)
    repo_common = _git_common_dir(repo_root)
    cutoff, cutoff_label = _parse_cutoff(before)

    selected_sources = {s.lower() for s in sources} if sources else None
    if box_action:
        with _prune_lock_if(not dry_run) as holds_lock:
            if holds_lock:
                pending = _boxes_of_removed_worktrees(load_worktree_boxes(), repo_root, repo_common, selected_sources)
                _clean_boxes_of_removed_worktrees(pending, box_action, cutoff, dry_run, yes)
            else:
                click.echo(
                    "A devbox prune is still running, so the devboxes of worktrees removed earlier were left for the next run.\n"
                )
    # ~/.cargo/target belongs to no single worktree or repository, so a run narrowed by --source or --repo leaves it alone.
    if mode != "full" and selected_sources is None and repo is None:
        _clean_legacy_cargo_target(cutoff, dry_run, yes)
    protected = _protected_paths(repo_root)

    registry = _registered_worktrees(repo_root)
    if registry is None:
        # We couldn't read git's worktree list, so we can't tell which worktrees
        # are locked. Refuse rather than risk deleting a locked worktree.
        click.echo("Could not read `git worktree list` for this repo; aborting to stay safe.")
        return

    busy = _process_cwds()
    if busy is None:
        click.echo("Could not list running processes, so no worktree can be shown to be idle; aborting to stay safe.")
        return
    leftovers = [
        path for path in _leftover_worktree_dirs(repo_root, selected_sources, cutoff) if not _in_use(path, busy)
    ]
    _clean_leftover_worktree_dirs(leftovers, dry_run, yes)
    in_use: list[Path] = []
    candidates: list[Worktree] = []
    for source, path in _discover_candidate_worktrees(repo_root, registry, selected_sources, mode, skip_hand_made):
        resolved = _resolve(path)
        if resolved in protected:
            continue
        # PostHog Desktop worktrees live outside the repo and the home root is
        # shared across repos, so only act on worktrees owned by this repo.
        if not _belongs_to_repo(resolved, repo_root, repo_common):
            continue
        meta = registry.get(resolved)
        if meta and meta["locked"]:
            continue  # never touch a git-locked worktree
        if _in_use(resolved, busy):
            in_use.append(path)
            continue
        candidates.append(
            Worktree(
                source=source,
                path=path,
                registered=meta is not None,
                locked=bool(meta and meta["locked"]),
                branch=(meta["branch"] if meta else ""),
                last_activity=_last_activity(path),
            )
        )

    if in_use:
        click.echo(f"Skipping {len(in_use)} worktree(s) that a running process has as its working directory:")
        for path in in_use:
            click.echo(f"  {_display_path(path)}")
        click.echo("")

    if not candidates:
        click.echo(f"No agent worktrees found for {_display_path(repo_root)}.")
        return

    stale = [wt for wt in candidates if wt.last_activity < cutoff]
    click.echo(f"Found {len(candidates)} worktree(s); {len(stale)} match the filter ({cutoff_label}).\n")
    if not stale:
        return

    stale = _without_cargo_builds(stale)
    if not stale:
        click.echo("Nothing left to remove.")
        return

    # Full mode is destructive of working-tree state, so refuse worktrees with
    # unsaved work — or whose git state we can't verify — unless the user opts in.
    # (deps mode only removes recreatable artifacts, so it doesn't need this gate.)
    if mode == "full":
        _populate_git_state(stale, _repo_has_remotes(repo_root))
        unsafe = [wt for wt in stale if wt.unsafe]
        if unsafe and not include_dirty:
            click.echo(f"Skipping {len(unsafe)} worktree(s) with unsaved work or unreadable git state:")
            for wt in sorted(unsafe, key=lambda w: w.last_activity):
                click.echo(f"  {wt.source}  {_display_path(wt.path)}  ({_state_markers(wt)})")
            click.echo("  Re-run with --include-dirty to remove them anyway.\n")
            stale = [wt for wt in stale if not wt.unsafe]
        if not stale:
            click.echo("Nothing left to remove.")
            return

    # Apply the orphan policy (both modes). Orphans are worktrees git no longer
    # tracks; their committed work survives in branch refs, so removing them only
    # discards uncommitted edits in an already-stale tree.
    orphan_wts = [wt for wt in stale if not wt.registered]
    if orphan_wts and not _include_orphans(orphan_policy, orphan_wts, dry_run, yes):
        stale = [wt for wt in stale if wt.registered]
        if not stale:
            click.echo("Nothing left to remove.")
            return

    click.echo(f"Measuring {len(stale)} worktree(s)…")
    _populate_sizes(stale, mode, cutoff)

    for wt in sorted(stale, key=lambda w: w.last_activity):
        markers = _listing_markers(wt, mode)
        click.echo(
            f"  {_format_size(wt.usage.freeable_bytes):>10}  {_ago(wt.last_activity):>12} ago  {markers}  {_display_path(wt.path)}"
        )

    total = sum((wt.usage for wt in stale), NO_USAGE)
    action = "fully remove" if mode == "full" else f"strip {_describe_artifact_kinds(mode)} from"
    click.echo(f"\nWould {action} {len(stale)} worktree(s), which frees about {_format_size(total.freeable_bytes)}.")
    shared_bytes = total.allocated_bytes - total.freeable_bytes
    if shared_bytes > 0:
        click.echo(
            f"Another {_format_size(shared_bytes)} in them shares its blocks with copies elsewhere, "
            "such as the pnpm or uv store, so deleting it frees nothing."
        )

    registered_boxes = _match_worktree_boxes(stale, load_worktree_boxes()) if mode == "full" else []
    boxes = registered_boxes if box_action else []
    if boxes:
        click.echo(f"\nWould {box_action} {len(boxes)} devbox(es) set up for these worktrees:")
        for box in boxes:
            click.echo(f"  {box.workspace}  {_display_path(box.checkout_path)}")

    if dry_run:
        click.echo("[DRY-RUN] Nothing deleted.")
        return

    box_prompt = f" and {box_action} {len(boxes)} devbox(es)" if boxes else ""
    if not yes and not click.confirm(
        f"\nProceed to {action} these {len(stale)} worktree(s){box_prompt}?", default=False
    ):
        click.echo("Aborted.")
        return

    # A build can start, or finish, while the prompt waits.
    stale = _without_cargo_builds(stale)
    for wt in stale:
        wt.artifact_items = [item for item in wt.artifact_items if not _cargo_built_since(item, cutoff)]
    if not stale:
        click.echo("Nothing left to remove.")
        return

    _remove_worktrees_and_their_boxes(stale, mode, repo_root, registered_boxes, box_action)


def _prune_lock_if(needed: bool) -> AbstractContextManager[bool]:
    return worktree_prune_lock(_PRUNE_LOCK_TIMEOUT_SECONDS) if needed else nullcontext(True)


def _remove_worktrees_and_their_boxes(
    stale: list[Worktree], mode: str, repo_root: Path, registered_boxes: list[WorktreeBox], box_action: str | None
) -> None:
    with _prune_lock_if(bool(registered_boxes)) as holds_lock:
        if not holds_lock:
            click.echo("A devbox prune is still running, so nothing was removed. Run this again in a few minutes.")
            return
        reap = _execute(
            stale,
            mode,
            repo_root,
            before_remove=lambda wt: _stop_worktree_mirrors(
                [box for box in registered_boxes if box.current_path == wt.path]
            ),
        )
        _add_reclaimed_properties(reap.reclaimed_bytes, reap.removed)
        if reap.reclaimed_bytes >= 0:
            summary = f"\n✓ Done. Reclaimed ~{_format_size(reap.reclaimed_bytes)} of disk across {reap.removed}/{len(stale)} worktree(s)."
        else:
            summary = (
                f"\n✓ Done. Removed {reap.removed}/{len(stale)} worktree(s) (reclaimed space could not be measured)."
            )
        failed = reap.failed
        if failed:
            summary += f" {failed} could not be fully removed (see warnings above)."
        click.echo(summary)

        removed_boxes = [box for box in registered_boxes if not box.checkout_path.exists()]
        if box_action and removed_boxes:
            _clean_worktree_boxes(removed_boxes, box_action)
        elif removed_boxes:
            # A box left alone on purpose must not look like a failed cleanup to a later run.
            forget_worktree_boxes({box.worktree_path: box.record for box in removed_boxes})
            names = " ".join(box.workspace for box in removed_boxes)
            click.echo(f"Left these devboxes as they are. worktrees:clean no longer tracks them: {names}")


def _resolve_box_action(stop_boxes: bool, delete_boxes: bool, keep_boxes: bool, mode: str) -> str | None:
    if sum([stop_boxes, delete_boxes, keep_boxes]) > 1:
        raise click.UsageError("Pass at most one of --stop-boxes, --delete-boxes, --keep-boxes.")
    if (stop_boxes or delete_boxes) and mode != "full":
        raise click.UsageError(
            f"--stop-boxes and --delete-boxes need --mode full, because --mode {mode} keeps the worktree."
        )
    if keep_boxes or mode != "full":
        return None
    if stop_boxes:
        return "stop"
    if delete_boxes:
        return "delete"
    return saved_worktree_box_cleanup()


def _boxes_of_removed_worktrees(
    registry: dict[str, WorktreeBoxRecord],
    repo_root: Path,
    repo_common: Path | None,
    selected_sources: set[str] | None,
) -> list[WorktreeBox]:
    """Registered boxes whose worktree is gone, limited to the selected repo and sources.

    The admin directory in the shared git dir survives a `git worktree move`,
    and Claude Code deletes a worktree's folder without it. So a worktree
    counts as removed when its admin directory is gone, or when `git worktree
    prune` would delete that directory. A record without a worktree ID cannot
    tell its admin directory from a reused one, so any directory at that path
    counts as its own.
    """
    if repo_common is None:
        return []
    boxes: list[WorktreeBox] = []
    for path, record in registry.items():
        admin_dir = Path(record.git_dir)
        admin_dir_is_its_own = record.tracks_worktree(admin_dir) if record.worktree_id else admin_dir.exists()
        worktree_is_live = admin_dir_is_its_own and not _git_would_prune(admin_dir)
        if (
            _holds_a_worktree(Path(path))
            or worktree_is_live
            or _resolve(admin_dir.parent.parent) != _resolve(repo_common)
        ):
            continue
        if selected_sources is not None and _source_under(_resolve(Path(path)), repo_root) not in selected_sources:
            continue
        boxes.append(WorktreeBox(worktree_path=Path(path), record=record))
    return boxes


def _holds_a_worktree(path: Path) -> bool:
    admin_dir = _gitdir_for(path)
    return admin_dir is not None and admin_dir.is_dir() and not _git_would_prune(admin_dir)


def _git_would_prune(admin_dir: Path) -> bool:
    """`git worktree prune`'s rule: the worktree is not locked, and its `gitdir` file is missing or names a missing path."""
    if (admin_dir / "locked").exists():
        return False
    try:
        checkout_git_file = Path((admin_dir / "gitdir").read_text().strip())
    except OSError:
        return True
    return not (admin_dir / checkout_git_file).exists()


def prune_boxes_of_removed_worktrees(
    repo_root: Path, box_action: str, worktree_path: Path | None, dry_run: bool
) -> list[WorktreeBox]:
    """Act on the boxes of this repo's worktrees that another tool already removed, or only the one at *worktree_path*.

    `worktrees:clean` covers worktrees it removes itself. t3code and herdr remove
    their own, so their boxes are found here by the same rule.
    """
    boxes = _boxes_of_removed_worktrees(load_worktree_boxes(), repo_root, _git_common_dir(repo_root), None)
    if worktree_path is not None:
        boxes = [box for box in boxes if _resolve(box.worktree_path) == _resolve(worktree_path)]
    if not boxes:
        return []
    click.echo(f"{len(boxes)} devbox(es) belong to worktrees that were already removed:")
    for box in boxes:
        click.echo(f"  {box.workspace}  {_display_path(box.worktree_path)}")
    if dry_run:
        click.echo(f"[DRY-RUN] Would {box_action} them.")
    else:
        _clean_worktree_boxes(boxes, box_action, require_removed=True)
    return boxes


def teardown_worktree_box(
    worktree_path: Path,
    git_dir: Path,
    box_action: str,
    dry_run: bool,
    keep_record: bool = False,
    act_on_box: Callable[[WorktreeBox, str], None] | None = None,
) -> WorktreeBox | None:
    """Stop the mirror and act on the box of the worktree at *worktree_path*, which a tool is about to remove.

    The mirror stops first, while the files still exist, for the reason in
    `_stop_worktree_mirrors`. The record is found by the ID in *git_dir*, so a
    moved worktree still finds its box, and a record saved for an earlier
    worktree at the same path does not match. *keep_record* keeps the record
    of a stopped box, for a tool that keeps the worktree and can restore it.
    *act_on_box* replaces the box action, so a caller can move it out of a
    tool's hook time limit.
    """
    worktree_id = read_worktree_id(git_dir)
    match = next(
        (
            (Path(path), record)
            for path, record in load_worktree_boxes().items()
            if worktree_id is not None and record.worktree_id == worktree_id
        ),
        None,
    )
    if match is None:
        return None
    box = WorktreeBox(worktree_path=match[0], record=match[1], current_path=worktree_path)
    if dry_run:
        click.echo(f"[DRY-RUN] Would stop the sync mirror and {box_action} {box.workspace}.")
        return box
    _stop_worktree_mirrors([box])
    if act_on_box is None:
        _clean_worktree_boxes([box], box_action, keep_stopped_records=keep_record)
    else:
        act_on_box(box, box_action)
    return box


def clean_registered_box(worktree_path: Path, worktree_id: str, box_action: str, keep_record: bool) -> None:
    """Act on the box registered for *worktree_path*, if the worktree with *worktree_id* still holds it.

    A worktree recreated at the same path can take the box over before this
    runs, and its record then carries its own ID.
    """
    record = load_worktree_boxes().get(str(worktree_path))
    if record is not None and record.worktree_id == worktree_id:
        _clean_worktree_boxes(
            [WorktreeBox(worktree_path=worktree_path, record=record)], box_action, keep_stopped_records=keep_record
        )


def _clean_boxes_of_removed_worktrees(
    boxes: list[WorktreeBox], box_action: str, cutoff: float, dry_run: bool, yes: bool
) -> None:
    """Act on the boxes of removed worktrees that have been idle since *cutoff*.

    The worktree is gone, so the box's own last use stands in for its age.
    """
    if not boxes:
        return
    click.echo(f"{len(boxes)} devbox(es) belong to worktrees that were already removed:")
    for box in boxes:
        click.echo(f"  {box.workspace}  {_display_path(box.worktree_path)}")
    if dry_run:
        which = "them" if cutoff == float("inf") else "the ones not used since the cutoff"
        click.echo(f"[DRY-RUN] Would {box_action} {which}.\n")
        return
    if yes or click.confirm(f"{box_action.capitalize()} them now?", default=False):
        _clean_worktree_boxes(boxes, box_action, idle_before=cutoff, require_removed=True)
    click.echo()


def _match_worktree_boxes(worktrees: list[Worktree], registry: dict[str, WorktreeBoxRecord]) -> list[WorktreeBox]:
    """Pair each worktree with the devbox registered for it.

    The match uses the ID that `devbox:worktree` stored in the worktree's admin
    directory. `git worktree move` carries that directory over, so a moved
    worktree still matches. A worktree recreated at a reused path gets a new,
    empty admin directory, so it never matches its predecessor's box.
    """
    registry_by_worktree_id = {
        record.worktree_id: (Path(path), record) for path, record in registry.items() if record.worktree_id
    }
    boxes: list[WorktreeBox] = []
    for wt in worktrees:
        git_dir = _gitdir_for(wt.path)
        worktree_id = read_worktree_id(git_dir) if git_dir is not None else None
        match = registry_by_worktree_id.get(worktree_id) if worktree_id is not None else None
        if match is not None:
            boxes.append(WorktreeBox(worktree_path=match[0], record=match[1], current_path=wt.path))
    return boxes


def _stop_worktree_mirrors(boxes: list[WorktreeBox]) -> None:
    """Stop the sync mirrors before their worktrees go away.

    A mirror that still runs while the local files disappear copies the
    deletions to the devbox, which would empty the checkout that `--stop-boxes`
    and `--keep-boxes` exist to keep.
    """
    for box in boxes:
        try:
            mutagen.sync_terminate(mutagen.workspace_label_selector(box.workspace))
        except SystemExit:
            click.echo(f"  ⚠️  could not stop the sync mirror for {box.workspace}; its devbox copy may lose files.")


def _box_last_used(workspace: Mapping[str, object]) -> float | None:
    last_used = workspace.get("last_used_at")
    if not isinstance(last_used, str):
        return None
    try:
        return datetime.fromisoformat(last_used).timestamp()
    except ValueError:
        return None


def _clean_worktree_boxes(
    boxes: list[WorktreeBox],
    box_action: str,
    idle_before: float = float("inf"),
    keep_stopped_records: bool = False,
    require_removed: bool = False,
) -> None:
    """Stop or delete *boxes* and forget their records.

    With *keep_stopped_records*, a box that ends up stopped keeps its record, so
    the worktree can start it again when a tool restores it. With
    *require_removed*, a box whose worktree came back while the provider was
    listed is left alone, because the new worktree may have taken the box over.
    """
    hogland_boxes = [box for box in boxes if box.record.provider == "hogland"]
    coder_boxes = [box for box in boxes if box.record.provider != "hogland"]
    if hogland_boxes:
        _clean_hogland_boxes(hogland_boxes, box_action, idle_before, keep_stopped_records, require_removed)
    if coder_boxes:
        _clean_coder_boxes(coder_boxes, box_action, idle_before, keep_stopped_records, require_removed)


def _worktree_came_back(box: WorktreeBox) -> bool:
    return _holds_a_worktree(box.worktree_path) or load_worktree_boxes().get(str(box.worktree_path)) != box.record


def _ready_to_act_on(
    box: WorktreeBox,
    listed: Mapping[str, object],
    idle_before: float,
    require_removed: bool,
    handled: dict[Path, WorktreeBoxRecord],
) -> bool:
    if not box.record.owns(listed):
        click.echo(f"  {box.workspace} was recreated after this worktree set it up, so it was left alone.")
        handled[box.worktree_path] = box.record
        return False
    last_used = _box_last_used(listed)
    if idle_before != float("inf") and (last_used is None or last_used >= idle_before):
        click.echo(f"  {box.workspace} was used after the cutoff, or its last use is unknown, so it was left alone.")
        return False
    if require_removed and _worktree_came_back(box):
        click.echo(f"  {box.workspace} belongs to a worktree at {box.worktree_path} again, so it was left alone.")
        return False
    try:
        mutagen.sync_terminate(mutagen.workspace_label_selector(box.workspace))
    except SystemExit:
        click.echo(f"  ⚠️  could not remove the sync mirror for {box.workspace}; continuing.")
    return True


def _clean_hogland_boxes(
    boxes: list[WorktreeBox], box_action: str, idle_before: float, keep_stopped_records: bool, require_removed: bool
) -> None:
    try:
        hogland.ensure_cli()
        devboxes = hogland.fetch_devboxes()
    except SystemExit:
        names = " ".join(box.workspace for box in boxes)
        click.echo(f"  ⚠️  could not reach Hogland, so these devboxes were left as they are: {names}")
        return
    handled: dict[Path, WorktreeBoxRecord] = {}
    for box in boxes:
        devbox = get_workspace(box.workspace, devboxes)
        if devbox is None:
            click.echo(f"  {box.workspace} no longer exists.")
            hogland.forget_ssh_entry(box.workspace)
            handled[box.worktree_path] = box.record
            continue
        if not _ready_to_act_on(box, devbox, idle_before, require_removed, handled):
            continue
        try:
            if box_action == "delete":
                click.echo(f"Deleting Hogland devbox {box.workspace}...")
                hogland.delete(box.workspace)
                hogland.forget_ssh_entry(box.workspace)
            elif devbox["status"] == "running":
                click.echo(f"Hibernating Hogland devbox {box.workspace}...")
                hogland.hibernate(box.workspace)
            else:
                click.echo(f"  {box.workspace} is already {devbox['status']}.")
        except SystemExit:
            command = "delete" if box_action == "delete" else "hibernate"
            click.echo(f"  ⚠️  could not {box_action} {box.workspace}. Run `hogland devbox {command} {box.workspace}`.")
            continue
        if box_action == "delete" or not keep_stopped_records:
            handled[box.worktree_path] = box.record
    forget_worktree_boxes(handled)


def _clean_coder_boxes(
    boxes: list[WorktreeBox], box_action: str, idle_before: float, keep_stopped_records: bool, require_removed: bool
) -> None:
    try:
        ensure_runtime_ready()
    except SystemExit:
        names = " ".join(box.workspace for box in boxes)
        click.echo(f"  ⚠️  could not reach Coder, so these devboxes were left as they are: {names}")
        return

    workspaces = fetch_user_workspaces()
    if workspaces is None:
        names = " ".join(box.workspace for box in boxes)
        click.echo(f"  ⚠️  could not list your devboxes, so these were left as they are: {names}")
        return
    handled: dict[Path, WorktreeBoxRecord] = {}
    for box in boxes:
        workspace = get_workspace(box.workspace, workspaces)
        if workspace is None:
            click.echo(f"  {box.workspace} no longer exists.")
            handled[box.worktree_path] = box.record
            continue
        if not _ready_to_act_on(box, workspace, idle_before, require_removed, handled):
            continue
        try:
            if box_action == "delete":
                click.echo(f"Deleting devbox {box.workspace}...")
                delete_workspace(box.workspace)
                herdr.forget_machine(box.workspace)
            elif get_workspace_status(workspace) != "stopped":
                click.echo(f"Stopping devbox {box.workspace}...")
                stop_workspace(box.workspace)
            else:
                click.echo(f"  {box.workspace} is already stopped.")
        except SystemExit:
            command = "devbox:destroy" if box_action == "delete" else "devbox:stop"
            label = extract_workspace_label(box.workspace) or ""
            click.echo(f"  ⚠️  could not {box_action} {box.workspace}. Run `hogli {command} {label}`.")
            continue
        if box_action == "delete" or not keep_stopped_records:
            handled[box.worktree_path] = box.record
    forget_worktree_boxes(handled)


def _resolve_orphan_policy(explicit: str | None, mode: str) -> str:
    """Resolve --orphans, defaulting per mode: deps and build clean orphans (they
    remove only recreatable artifacts), full prompts (it deletes the working copy)."""

    if explicit is not None:
        return explicit.lower()
    return "ask" if mode == "full" else "yes"


_UNATTENDED_SCHEDULE = (("14d", "full"), ("7d", "deps,build"))
# .flox/env/on-activate.sh checks this file's mtime before it spawns hogli.
_UNATTENDED_LOCK = Path.home() / ".config" / "posthog" / "worktrees-clean.lock"
_PRUNE_LOCK_TIMEOUT_SECONDS = 300.0


def _unattended_lock(dry_run: bool) -> IO[str] | None:
    """The lock for one --unattended run a day, or None when one is running or ran today.

    The caller holds it until the process exits, so a second shell that activates
    in the same second backs off instead of removing the same paths. The file
    holds the epoch of the last real run, so a dry run never consumes the day."""

    _UNATTENDED_LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = _UNATTENDED_LOCK.open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    lock.seek(0)
    try:
        last_run = float(lock.read().strip() or 0)
    except ValueError:
        last_run = 0.0
    if time.time() - last_run < 24 * 60 * 60:
        lock.close()
        return None
    if not dry_run:
        lock.truncate(0)
        lock.write(str(time.time()))
        lock.flush()
    return lock


def _include_orphans(policy: str, orphans: list[Worktree], dry_run: bool, yes: bool) -> bool:
    """Resolve the --orphans policy to a keep/skip decision for orphaned worktrees."""

    if policy == "yes":
        return True
    if policy == "no":
        click.echo(f"Skipping {len(orphans)} orphaned worktree(s) (--orphans no).\n")
        return False

    # ask: surface the orphans, then decide. We can't prompt under --dry-run
    # (preview) or --yes (non-interactive), so both resolve to include.
    click.echo(f"{len(orphans)} orphaned worktree(s) found (git no longer tracks them; committed work is safe):")
    for wt in sorted(orphans, key=lambda w: w.last_activity):
        click.echo(f"  {wt.source}  {_ago(wt.last_activity):>10} ago  {_display_path(wt.path)}")
    if dry_run:
        click.echo("  (--orphans ask: you'll be prompted before deletion; counted as included below.)\n")
        return True
    if yes:
        click.echo("  Including them (--yes).\n")
        return True
    decision = click.confirm("Include these orphaned worktree(s)?", default=True)
    click.echo("")
    return decision


def _resolve_repo(repo: str | None) -> Path:
    """Resolve --repo (or the current dir) to its repo's *main* worktree root.

    Using the main worktree root (derived from the common git dir) means the
    command works the same whether invoked from the main checkout or from inside
    a linked worktree.
    """

    if repo is None:
        base = _resolve(REPO_ROOT)
    else:
        base = Path(repo).expanduser()
        if not base.is_dir():
            raise click.BadParameter(f"{repo!r} is not an existing directory.")

    common = _git_common_dir(base)
    if common is None:
        raise click.BadParameter(f"{repo or base!r} is not inside a git repository.")
    # The common dir of any worktree is `<main>/.git`; its parent is the main root.
    if common.name == ".git":
        return common.parent

    # Bare or unusual layout — fall back to the working-tree top level.
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        top = ""
    return _resolve(Path(top)) if top else _resolve(base)


def _git_common_dir(start: Path) -> Path | None:
    """Absolute shared git dir for the repo containing *start*, or None."""

    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=start,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not out:
        return None
    common = Path(out)
    if not common.is_absolute():
        common = start / common
    return _resolve(common)


def _parse_mode(value: str) -> str:
    """Normalize --mode to ``full`` or a comma list of artifact kinds in a fixed order, such as ``deps,build``."""

    parts = {part.strip().lower() for part in value.split(",") if part.strip()}
    unknown = parts - {"full", *ARTIFACT_KINDS}
    if not parts or unknown:
        raise click.BadParameter(f"{value!r} is not full, deps, build, or a comma list of deps and build.")
    if "full" in parts:
        if len(parts) > 1:
            raise click.BadParameter("full removes the whole worktree, so it cannot be combined with deps or build.")
        return "full"
    return ",".join(kind for kind in ARTIFACT_KINDS if kind in parts)


def _artifact_kinds(mode: str) -> frozenset[str]:
    return frozenset(mode.split(",")) & frozenset(ARTIFACT_KINDS)


def _describe_artifact_kinds(mode: str) -> str:
    labels = {"deps": "dependencies", "build": "build output"}
    return " and ".join(labels[kind] for kind in ARTIFACT_KINDS if kind in _artifact_kinds(mode))


def _parse_cutoff(value: str) -> tuple[float, str]:
    """Parse --before into (cutoff_epoch, human_label). Raises click.BadParameter on garbage."""

    raw = value.strip()
    lowered = raw.lower()
    if lowered == "all":
        return float("inf"), "all ages"

    interval = re.fullmatch(r"(\d+)([smhdw])", lowered)
    if interval:
        amount = int(interval.group(1))
        if amount == 0:
            raise click.BadParameter("a zero interval would match everything; use 'all' if that's intended.")
        seconds = amount * _INTERVAL_UNITS[interval.group(2)]
        return time.time() - seconds, f"idle older than {amount}{interval.group(2)}"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as err:
        raise click.BadParameter(f"{value!r} is not a date (YYYY-MM-DD), an interval (3h, 7d, 2w), or 'all'.") from err
    cutoff = parsed.timestamp()
    if cutoff > time.time():
        raise click.BadParameter(
            f"{value!r} is in the future and would match everything; use 'all' if that's intended."
        )
    return cutoff, f"last active before {parsed.date()}"


def _discover_worktrees(root: Path, max_depth: int = 2) -> list[Path]:
    """Find worktree directories under *root* (a dir containing a .git entry).

    Depth 1 covers Claude/Codex (root/<name>); depth 2 covers PostHog Desktop
    (root/<id>/posthog). Found worktrees are not descended into.
    """

    found: list[Path] = []
    if not root.is_dir():
        return found

    def scan(directory: Path, depth: int) -> None:
        try:
            entries = list(directory.iterdir())
        except (PermissionError, OSError):
            return
        for child in entries:
            if child.is_symlink() or not child.is_dir():
                continue
            if (child / ".git").exists():
                found.append(child)
            elif depth < max_depth:
                scan(child, depth + 1)

    scan(root, 1)
    return found


def _discover_candidate_worktrees(
    repo_root: Path,
    registry: dict[Path, dict],
    selected_sources: set[str] | None,
    mode: str,
    skip_hand_made: bool = False,
) -> list[tuple[str, Path]]:
    """Worktrees under the known tool roots, then the ones that `git worktree list` registers anywhere else.

    A worktree outside every tool root is one a person made by hand, so --mode
    full and the unattended run act on it only when --source other asks for it.
    """

    discovered: list[tuple[str, Path]] = []
    resolved_roots = [_resolve(root) for _, root in _worktree_roots(repo_root)]
    for source, root in _worktree_roots(repo_root):
        if selected_sources is None or source in selected_sources:
            discovered.extend((source, path) for path in _discover_root_worktrees(root, registry))
    include_other = (
        "other" in selected_sources if selected_sources is not None else not (mode == "full" or skip_hand_made)
    )
    if include_other:
        for path in registry:
            if path.is_dir() and not any(_is_under(path, root) for root in resolved_roots):
                discovered.append(("other", path))
    return discovered


def _discover_root_worktrees(root: Path, registry: dict[Path, dict]) -> list[Path]:
    found = _discover_worktrees(root, max_depth=_SCRATCHPAD_DISCOVERY_DEPTH if root == _claude_scratchpad_root() else 2)
    seen = {_resolve(path) for path in found}
    resolved_root = _resolve(root)
    for path in registry:
        if path not in seen and path != resolved_root and _is_under(path, resolved_root) and path.is_dir():
            found.append(path)
    return found


def _registered_worktrees(repo_root: Path) -> dict[Path, dict] | None:
    """Map resolved worktree path -> {locked, branch} from `git worktree list`.

    Returns None if git could not be queried (so callers can refuse rather than
    treat every worktree as unlocked).
    """

    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    registry: dict[Path, dict] = {}
    current: dict | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = _resolve(Path(line[len("worktree ") :]))
            current = {"locked": False, "branch": ""}
            registry[path] = current
        elif current is None:
            continue
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].removeprefix("refs/heads/")
        elif line == "detached":
            current["branch"] = "(detached)"
        elif line.startswith("locked"):
            current["locked"] = True
    return registry


def _leftover_worktree_dirs(repo_root: Path, selected_sources: set[str] | None, cutoff: float) -> list[Path]:
    """Folders where a worktree was, that now hold only the flox caches its removal could not delete.

    Go writes its module cache without write permission, which stopped earlier
    removals part way. A worktree root in the home directory is shared across
    repos, so there a folder counts only when it carries this repo's name, as
    the worktrees there do.
    """

    leftovers: list[Path] = []
    for source, root in _worktree_roots(repo_root):
        if source in ("phw", "claude-scratchpad") or (selected_sources is not None and source not in selected_sources):
            continue
        if _is_under(_resolve(root), repo_root):
            candidates = _child_dirs(root)
        else:
            candidates = [child / repo_root.name for child in _child_dirs(root)]
        for candidate in candidates:
            if _holds_only_flox_caches(candidate) and _newest_mtime([candidate, candidate / ".flox"]) < cutoff:
                leftovers.append(candidate)
    return leftovers


def _child_dirs(directory: Path) -> list[Path]:
    try:
        return [child for child in directory.iterdir() if child.is_dir() and not child.is_symlink()]
    except OSError:
        return []


def _holds_only_flox_caches(directory: Path) -> bool:
    try:
        if {entry.name for entry in directory.iterdir()} != {".flox"}:
            return False
        if {entry.name for entry in (directory / ".flox").iterdir()} != {"cache"}:
            return False
        cache_entries = {entry.name for entry in (directory / ".flox" / "cache").iterdir()}
    except OSError:
        return False
    return bool(cache_entries) and cache_entries <= FLOX_CACHE_ARTIFACTS.keys()


def _newest_mtime(paths: Sequence[Path]) -> float:
    try:
        return max(path.stat().st_mtime for path in paths)
    except OSError:
        return float("inf")


def _clean_leftover_worktree_dirs(leftovers: list[Path], dry_run: bool, yes: bool) -> None:
    if not leftovers:
        return
    size = measure_disk_usage(leftovers).freeable_bytes
    click.echo(
        f"{len(leftovers)} folder(s) of removed worktrees hold only flox caches ({_format_size(size)} to free), "
        "because Go's read-only module cache stopped their removal:"
    )
    for leftover in leftovers[:5]:
        click.echo(f"  {_display_path(leftover)}")
    if len(leftovers) > 5:
        click.echo(f"  … and {len(leftovers) - 5} more")
    if dry_run:
        click.echo("[DRY-RUN] Not deleted.\n")
        return
    if not yes and not click.confirm("Delete them?", default=False):
        click.echo()
        return
    failed = _delete_paths(leftovers)
    for leftover in leftovers:
        _cleanup_empty_parent(leftover)
    click.echo(f"✓ Deleted {len(leftovers) - failed} folder(s).\n")


def _protected_paths(repo_root: Path) -> set[Path]:
    """Worktrees that must never be deleted: the main repo and the current one."""

    protected = {_resolve(repo_root), _resolve(Path.cwd())}
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if top:
            protected.add(_resolve(Path(top)))
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return protected


def _resolve(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def _add_reclaimed_properties(reclaimed_bytes: float, removed: int) -> None:
    """Sum across the tiers of one --unattended run, which share one command_completed event."""

    ctx = click.get_current_context(silent=True)
    so_far = (ctx.meta.get(telemetry.COMMAND_PROPERTIES_META_KEY) if ctx else None) or {}
    telemetry.add_command_properties(worktrees_removed=so_far.get("worktrees_removed", 0) + removed)
    if reclaimed_bytes >= 0:
        telemetry.add_command_properties(reclaimed_gb=round(so_far.get("reclaimed_gb", 0.0) + reclaimed_bytes / 1e9, 2))


def _process_cwds() -> set[Path] | None:
    """Working directories of every process this user can see, or None when they
    cannot be listed.

    A dev server, editor or agent session sitting in a worktree leaves no git
    activity, so its working directory is the only sign the worktree is in use.
    This process is in the list too, so an empty result means the listing failed."""

    cwds: set[Path] = set()
    if sys.platform == "linux":
        for proc in Path("/proc").glob("[0-9]*"):
            try:
                cwds.add((proc / "cwd").readlink())
            except OSError:
                continue
    else:
        try:
            result = subprocess.run(["lsof", "-a", "-d", "cwd", "-F", "n"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        cwds = {Path(line[1:]) for line in result.stdout.splitlines() if line.startswith("n/")}
    return cwds or None


def _in_use(worktree: Path, cwds: set[Path]) -> bool:
    return any(cwd.is_relative_to(worktree) for cwd in cwds)


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(_resolve(parent))
        return True
    except ValueError:
        return False


def _belongs_to_repo(resolved_path: Path, repo_root: Path, repo_common: Path | None) -> bool:
    """Whether a worktree is owned by *repo_root*.

    Worktrees physically inside the repo always belong to it. For out-of-repo
    worktrees (PostHog Desktop's home root is shared across repos), confirm via the
    gitdir's commondir pointing back at this repo's common git directory. A
    dangling pointer we can't attribute is treated as not ours, so we never
    delete another repo's worktree.
    """

    if _is_under(resolved_path, repo_root):
        return True
    if repo_common is None:
        return False
    gitdir = _gitdir_for(resolved_path)
    if gitdir is None:
        return False
    common = _common_git_dir(gitdir)
    return common is not None and common == repo_common


def _common_git_dir(gitdir: Path) -> Path | None:
    """Resolve a per-worktree gitdir to its shared common git dir via commondir."""

    try:
        rel = (gitdir / "commondir").read_text().strip()
    except (OSError, ValueError):
        return None
    return _resolve(gitdir / rel)


def _last_activity(path: Path) -> float:
    """Most recent activity signal for a worktree (max of all available signals).

    Combines git activity (mtimes inside the per-worktree gitdir: HEAD, index,
    logs/HEAD, FETCH_HEAD, ...), the Claude Code session transcript mtime if one
    exists for this path, and the worktree directory mtime as a fallback. When no
    signal is readable we return +inf (never stale) so an unreadable worktree
    fails toward keeping rather than deletion.
    """

    times: list[float] = []

    gitdir = _gitdir_for(path)
    if gitdir is not None and gitdir.is_dir():
        try:
            times.append(gitdir.stat().st_mtime)
        except OSError:
            pass
        for name in ("HEAD", "index", "ORIG_HEAD", "FETCH_HEAD", "logs/HEAD"):
            entry = gitdir / name
            try:
                times.append(entry.stat().st_mtime)
            except OSError:
                continue

    transcript = _claude_transcript_mtime(path)
    if transcript is not None:
        times.append(transcript)

    try:
        times.append(path.stat().st_mtime)
    except OSError:
        pass

    return max(times) if times else float("inf")


def _gitdir_for(path: Path) -> Path | None:
    """Resolve a worktree's gitdir from its `.git` pointer file (or dir)."""

    dot_git = path / ".git"
    try:
        if dot_git.is_dir():
            return dot_git
        content = dot_git.read_text().strip()
    except (OSError, ValueError):
        return None
    if content.startswith("gitdir:"):
        target = Path(content[len("gitdir:") :].strip())
        if not target.is_absolute():
            target = (path / target).resolve()
        return target
    return None


def _claude_transcript_mtime(path: Path) -> float | None:
    """Newest Claude Code transcript mtime for *path*, if any.

    Claude stores transcripts under ~/.claude/projects/<encoded>/, where the
    encoding replaces every non-alphanumeric character in the absolute path with
    a dash. We match the encoded directory case-insensitively so the signal still
    works on case-sensitive filesystems (Linux) and when the recorded path case
    differs from the resolved one.
    """

    encoded = re.sub(r"[^a-zA-Z0-9]", "-", str(_resolve(path)))
    projects = Path.home() / ".claude" / "projects"
    project_dir = projects / encoded
    if not project_dir.is_dir():
        project_dir = _find_dir_case_insensitive(projects, encoded)
        if project_dir is None:
            return None
    mtimes = [t.stat().st_mtime for t in project_dir.glob("*.jsonl") if t.is_file()]
    return max(mtimes) if mtimes else None


def _find_dir_case_insensitive(parent: Path, name: str) -> Path | None:
    folded = name.casefold()
    try:
        for child in parent.iterdir():
            if child.name.casefold() == folded and child.is_dir():
                return child
    except (OSError, PermissionError):
        return None
    return None


def _populate_git_state(worktrees: list[Worktree], has_remotes: bool) -> None:
    """Fill in dirty / unpushed / detached / state_unknown for each worktree."""

    if not worktrees:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(worktrees))) as pool:
        list(pool.map(lambda wt: _compute_git_state(wt, has_remotes), worktrees))


def _compute_git_state(wt: Worktree, has_remotes: bool) -> None:
    # status.showUntrackedFiles=no would hide new files, and --force removes them without asking.
    status = _git(wt.path, ["status", "--porcelain", "--untracked-files=normal"])
    if status is not None and status.returncode == 0:
        wt.dirty = bool(status.stdout.strip())

        # symbolic-ref returns 1 for a genuine detached HEAD (status succeeded, so
        # this isn't the "git can't read it" 128 case).
        symref = _git(wt.path, ["symbolic-ref", "-q", "HEAD"])
        wt.detached = symref is not None and symref.returncode == 1

        # Commits reachable from HEAD but not on any remote — unpushed work a
        # forced removal would orphan. Meaningless without remotes (every commit
        # would count as unpushed), so skip the check when the repo has none.
        if has_remotes:
            ahead = _git(wt.path, ["rev-list", "--count", "HEAD", "--not", "--remotes"])
            if ahead is None or ahead.returncode != 0:
                wt.state_unknown = True
            else:
                count = ahead.stdout.strip()
                wt.unpushed = int(count) if count.isdigit() else 0
                if wt.unpushed:
                    wt.squash_merged = _squash_merge(wt.path)
        return

    # git couldn't read the worktree's status. Distinguish two cases:
    #  - Orphaned (its admin gitdir was pruned): git has already discarded this
    #    worktree's HEAD/index, and deleting the directory never touches refs, so
    #    committed work survives in the shared repo's branch. Only uncommitted
    #    edits in an already age-stale tree could be lost — safe to remove by
    #    default (it shows as "orphaned" in the listing).
    #  - gitdir still present (corruption, lock, or a status timeout): git should
    #    have been able to read it, so we can't confirm it's clean → fail closed.
    gitdir = _gitdir_for(wt.path)
    if gitdir is None or gitdir.is_dir():
        wt.state_unknown = True


def _repo_has_remotes(repo_root: Path) -> bool:
    result = _git(repo_root, ["remote"])
    return result is not None and result.returncode == 0 and bool(result.stdout.strip())


def _git(cwd: Path, args: Sequence[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str] | None:
    # A plain `git status` refreshes the index, and the index mtime is one of the worktree's activity signals.
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            errors="surrogateescape",
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


# A branch with more changed files than this is no squash merge to look for, and its file list would
# not fit one git command line.
_SQUASH_MAX_FILES = 1000
_SQUASH_MAX_CANDIDATES = 2000


def _squash_merge(worktree: Path) -> str | None:
    """Where the unpushed commits of *worktree* landed through a squash merge, or None.

    The merge queue lands a pull request as one new commit on the default branch
    and deletes the branch. The branch's own commits are then on no remote and
    are not ancestors of the default branch, although the work is merged.

    The offline check compares the patch id (a stable hash of a diff) of the
    branch's whole change with the default-branch commits since the branch left
    it that touch the same files. It misses a merge whose diff the queue changed,
    for example by resolving a conflict. The GitHub CLI, when it is installed and
    logged in, then looks for a merged pull request that contains HEAD.
    """

    head = _git(worktree, ["rev-parse", "HEAD"])
    if head is None or head.returncode != 0:
        return None
    sha = head.stdout.strip()
    default = _default_branch_ref(worktree)
    if default is None:
        return None
    commit = _squash_commit(worktree, sha, default)
    if commit is not None:
        return commit[:10]
    return _merged_pull_request(worktree, sha, default.removeprefix("origin/"))


def _default_branch_ref(worktree: Path) -> str | None:
    symbolic = _git(worktree, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if symbolic is not None and symbolic.returncode == 0 and symbolic.stdout.strip():
        return symbolic.stdout.strip()
    for candidate in ("origin/master", "origin/main"):
        verified = _git(worktree, ["rev-parse", "--verify", "--quiet", candidate])
        if verified is not None and verified.returncode == 0:
            return candidate
    return None


def _squash_commit(worktree: Path, head: str, default: str) -> str | None:
    base = _git(worktree, ["merge-base", default, head])
    if base is None or base.returncode != 0:
        return None
    fork_point = base.stdout.strip()
    changed = _git(worktree, ["diff", "--name-only", "--no-renames", fork_point, head])
    if changed is None or changed.returncode != 0:
        return None
    files = changed.stdout.splitlines()
    if not files or len(files) > _SQUASH_MAX_FILES:
        return None
    own = _patch_ids(worktree, ["diff", "--no-renames", fork_point, head])
    if not own:
        return None
    candidates = _patch_ids(
        worktree,
        [
            "log",
            "-p",
            "--no-renames",
            "--format=commit %H",
            "-n",
            str(_SQUASH_MAX_CANDIDATES),
            f"{fork_point}..{default}",
            "--",
            *files,
        ],
    )
    commit = candidates.get(next(iter(own)))
    if commit is None or not _contains_branch(worktree, commit, head):
        return None
    return commit


def _contains_branch(worktree: Path, commit: str, head: str) -> bool:
    """Whether merging *head* into *commit* changes nothing.

    A patch id leaves out where each hunk applies, so an edit moved to another block with the same
    context lines has the id of the squash it no longer matches. Merging catches that."""

    merged = _git(worktree, ["merge-tree", "--write-tree", commit, head])
    tree = _git(worktree, ["rev-parse", f"{commit}^{{tree}}"])
    if merged is None or tree is None or merged.returncode != 0 or tree.returncode != 0:
        return False
    return merged.stdout.split("\n", 1)[0].strip() == tree.stdout.strip()


def _patch_ids(cwd: Path, git_args: Sequence[str], timeout: float = 120.0) -> dict[str, str]:
    """The commit of each patch id among the patches that ``git <git_args>`` prints, the first one per id.

    The patches stream straight into ``git patch-id``: a long history of a big, often rewritten file
    would not fit in memory, and several worktrees are checked at once.
    Diffs are bytes, not text: a binary or non-UTF-8 file would make a text decode fail.
    --verbatim keeps whitespace in the id, so a re-indent committed after the merge does not match it."""

    try:
        with subprocess.Popen(["git", *git_args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as patch:
            try:
                ids = subprocess.run(
                    ["git", "patch-id", "--verbatim"],
                    cwd=cwd,
                    stdin=patch.stdout,
                    capture_output=True,
                    timeout=timeout,
                )
                # Closed here too, so git exits on a broken pipe instead of blocking if patch-id stopped reading.
                patch.stdout.close()
                if patch.wait(timeout=timeout) != 0:
                    return {}
            except subprocess.TimeoutExpired:
                # Leaving the with block waits for git without a timeout, so a stalled git is killed first.
                patch.kill()
                return {}
    except (FileNotFoundError, OSError):
        return {}
    commits: dict[str, str] = {}
    for line in ids.stdout.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 2:
            commits.setdefault(parts[0], parts[1])
    return commits


def _merged_pull_request(worktree: Path, head: str, base: str) -> str | None:
    """A pull request merged into *base* that contains HEAD. A stacked pull request merged into a
    branch that never reached *base* does not count."""

    gh = shutil.which("gh")
    if gh is None:
        return None
    # The search also matches pull requests that only mention the hash, so HEAD must be one of the commits.
    query = f'[.[] | select(any(.commits[]; .oid == "{head}")) | .number][0] // empty'
    try:
        result = subprocess.run(
            [
                gh,
                "pr",
                "list",
                "--state",
                "merged",
                "--base",
                base,
                "--search",
                head,
                "--json",
                "number,commits",
                "--jq",
                query,
            ],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    number = result.stdout.strip()
    return f"#{number}" if result.returncode == 0 and number.isdigit() else None


def _state_markers(wt: Worktree) -> str:
    parts: list[str] = []
    if wt.dirty:
        parts.append("uncommitted changes")
    if wt.unpushed:
        parts.append(
            f"{wt.unpushed} unpushed commit(s)" + (f" merged as {wt.squash_merged}" if wt.squash_merged else "")
        )
    if wt.detached:
        parts.append("detached HEAD")
    if wt.state_unknown:
        parts.append("git state unreadable")
    return ", ".join(parts) if parts else "clean"


def _listing_markers(wt: Worktree, mode: str) -> str:
    parts = [wt.source]
    if not wt.registered:
        parts.append("orphaned")
    if wt.branch and wt.branch != "(detached)":
        parts.append(wt.branch)
    if mode == "full":
        if wt.dirty:
            parts.append("dirty")
        if wt.unpushed and wt.squash_merged:
            parts.append(f"merged as {wt.squash_merged}")
        elif wt.unpushed:
            parts.append(f"{wt.unpushed} unpushed")
        if wt.detached:
            parts.append("detached")
        if wt.state_unknown:
            parts.append("unreadable")
    return " · ".join(parts)


def _populate_sizes(worktrees: list[Worktree], mode: str, cutoff: float) -> None:
    """Fill in .usage, and the artifact items outside full mode, using a thread pool."""

    def work(wt: Worktree) -> None:
        if mode == "full":
            wt.usage = measure_disk_usage([wt.path])
        else:
            artifacts = _git_approved_artifacts(wt.path, _collect_artifacts(wt.path, _artifact_kinds(mode)))
            wt.artifact_items = [item for item in artifacts if not _cargo_built_since(item, cutoff)]
            wt.usage = measure_disk_usage(wt.artifact_items)

    if not worktrees:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(worktrees))) as pool:
        list(pool.map(work, worktrees))


@dataclass(frozen=True, kw_only=True, slots=True)
class _Artifact:
    path: Path
    kinds: frozenset[str]


def _collect_artifacts(worktree: Path, kinds: frozenset[str]) -> list[_Artifact]:
    """Find the dependency and build-output paths of the selected *kinds* inside a worktree.

    Every returned path is resolved and confirmed to stay within the worktree, so
    a symlinked component (e.g. a `frontend` symlinked to shared storage) can
    never cause deletion outside the worktree. The walk does not enter another
    repository, submodule or worktree nested inside this one.
    """

    worktree_resolved = _resolve(worktree)
    found: dict[Path, frozenset[str]] = {}

    def add(candidate: Path, rule_kinds: frozenset[str]) -> None:
        selected = rule_kinds & kinds
        if not selected:
            return
        # A symlinked artifact name points at another folder, which may be someone's work, so only real folders count.
        if candidate.is_symlink():
            return
        resolved = _resolve(candidate)
        if _is_under(resolved, worktree_resolved) and resolved.exists():
            found.setdefault(resolved, selected)

    for dirpath, dirnames, filenames in os.walk(worktree):
        parent = Path(dirpath)
        descend: list[str] = []
        for name in dirnames:
            child = parent / name
            if (child / ".git").exists():
                continue
            if name == ".flox":
                for cache_child, rule_kinds in FLOX_CACHE_ARTIFACTS.items():
                    add(child / "cache" / cache_child, rule_kinds)
                continue
            rule = ARTIFACT_DIRS.get(name)
            if rule is not None and rule.applies_to(child):
                add(child, rule.kinds)
                continue
            if name in _WALK_SKIP:
                continue
            descend.append(name)
        dirnames[:] = descend
        for name in filenames:
            if name.endswith(BUILD_FILE_SUFFIXES):
                add(parent / name, _BUILD)

    for pattern in BUILD_EXPLICIT_PATHS:
        for path in worktree.glob(pattern):
            if path.is_dir():
                add(path, _BUILD)

    outermost = sorted(found, key=lambda path: len(path.parts))
    kept: list[_Artifact] = []
    kept_paths: set[Path] = set()
    for path in outermost:
        if not any(ancestor in kept_paths for ancestor in path.parents):
            kept_paths.add(path)
            kept.append(_Artifact(path=path, kinds=found[path]))
    return kept


def _git_approved_artifacts(worktree: Path, artifacts: list[_Artifact]) -> list[Path]:
    """The artifacts that hold no tracked file and, unless they are dependencies, hold only files that git ignores.

    A generated file that the repo commits, or a file git does not ignore, may be
    someone's work, so a path that holds one stays. A dependency folder may be
    outside .gitignore, because no one writes their own files into one. When
    git cannot answer, nothing is approved, and that includes an orphaned
    worktree, whose lost index leaves git unable to say what its branch tracks.
    """

    if not artifacts:
        return []
    gitdir = _gitdir_for(worktree)
    if gitdir is None or not gitdir.is_dir():
        click.echo(f"  {_display_path(worktree)} is orphaned, so git cannot check it and nothing in it is removed.")
        return []
    status = _git(
        worktree, ["status", "--porcelain=v1", "-z", "--ignored=traditional", "--untracked-files=normal"], timeout=120.0
    )
    if status is None or status.returncode != 0:
        click.echo(f"  ⚠️  git could not list what {_display_path(worktree)} ignores, so nothing in it is removed.")
        return []

    untracked: set[str] = set()
    ignored: set[str] = set()
    entries = iter(status.stdout.split("\0"))
    for entry in entries:
        code, path = entry[:2], entry[3:].rstrip("/")
        if code == "??":
            untracked.add(path)
        elif code == "!!":
            ignored.add(path)
        elif "R" in code or "C" in code:
            next(entries, None)

    worktree_resolved = _resolve(worktree)
    approved: list[Path] = []
    for artifact in artifacts:
        if _holds_nested_repo(artifact.path):
            continue
        relative = artifact.path.relative_to(worktree_resolved).as_posix()
        if _is_or_is_under_any(relative, ignored) or (
            "deps" in artifact.kinds and _is_or_is_under_any(relative, untracked)
        ):
            approved.append(artifact.path)
    return approved


def _holds_nested_repo(artifact: Path) -> bool:
    """Whether a repo that git does not see from outside sits near the top of *artifact*, such as a pip editable install in .venv/src."""

    return artifact.is_dir() and any(
        True for pattern in ("*/.git", "*/*/.git", "*/*/*/.git") for _ in itertools.islice(artifact.glob(pattern), 1)
    )


def _is_or_is_under_any(relative_path: str, directories: set[str]) -> bool:
    while relative_path:
        if relative_path in directories:
            return True
        relative_path = relative_path.rpartition("/")[0]
    return False


def _without_cargo_builds(worktrees: list[Worktree]) -> list[Worktree]:
    building = worktrees_running_cargo([wt.path for wt in worktrees])
    if building is None:
        click.echo("Could not find the directory of every running cargo or rustc process, so no worktree is changed.\n")
        return []
    if building:
        click.echo(f"Skipping {len(building)} worktree(s) where cargo is running:")
        for wt in worktrees:
            if wt.path in building:
                click.echo(f"  {wt.source}  {_display_path(wt.path)}")
        click.echo()
    return [wt for wt in worktrees if wt.path not in building]


def _cargo_built_since(path: Path, cutoff: float) -> bool:
    return path.name == "target" and looks_like_cargo_target(path) and last_cargo_build_epoch(path) >= cutoff


def _clean_legacy_cargo_target(cutoff: float, dry_run: bool, yes: bool) -> None:
    target = unused_legacy_cargo_target(cutoff)
    if target is None:
        return

    size = measure_disk_usage([target]).freeable_bytes
    click.echo(
        f"Old shared Cargo target {_display_path(target)}: {_format_size(size)}, "
        f"last build {_ago(last_cargo_build_epoch(target))} ago. Cargo built here while the Flox env set CARGO_TARGET_DIR."
    )
    if dry_run:
        click.echo("[DRY-RUN] Not deleted.\n")
        return
    if not yes and not click.confirm("Delete it?", default=False):
        click.echo()
        return
    if unused_legacy_cargo_target(cutoff) is None:
        click.echo("A build used it while the prompt waited, so it is kept.\n")
        return
    if _delete_paths([target]) == 0:
        click.echo(f"✓ Deleted {_display_path(target)}.")
    click.echo()


def _execute(
    worktrees: list[Worktree],
    mode: str,
    repo_root: Path,
    before_remove: Callable[[Worktree], None] = lambda wt: None,
) -> _ReapResult:
    """Delete the selected worktrees (or their deps).

    ``before_remove`` runs for each worktree that passed the final in-use check,
    so a worktree kept at the last moment keeps its sync mirror too.

    The reclaimed figure is measured from actual filesystem free space before/after,
    so it reflects what was genuinely freed — hardlinked (pnpm store) and
    copy-on-write-cloned (APFS) blocks that are shared elsewhere don't count. Falls
    back to -1.0 if free space couldn't be measured.
    """

    # Anchor on each target's parent (which survives the deletion) so disk_usage
    # has a readable path on the same filesystem before and after.
    anchors = [wt.path.parent for wt in worktrees]
    before = _free_by_device(anchors)

    removed = 0
    failed = 0
    need_prune = False

    for wt in worktrees:
        busy = _process_cwds()
        if busy is None:
            click.echo("Could not list running processes; leaving the remaining worktree(s) in place.")
            break
        if _in_use(_resolve(wt.path), busy):
            click.echo(f"  skipped {_display_path(wt.path)}: a running process now has it as its working directory")
            continue
        before_remove(wt)
        if mode != "full":
            # Git can start tracking a path while the prompt waits, so only paths that git still approves now go.
            still_approved = set(_git_approved_artifacts(wt.path, _collect_artifacts(wt.path, _artifact_kinds(mode))))
            items = [item for item in wt.artifact_items if item in still_approved]
            if not items:
                continue
            if _delete_paths(items):
                failed += 1
            else:
                removed += 1
            continue

        if wt.registered:
            subprocess.run(
                ["git", "worktree", "remove", "--force", "--", str(wt.path)],
                cwd=repo_root,
                capture_output=True,
            )
            # git cannot delete read-only directories, so `_rmtree` below removes what it leaves
            # behind. Prune the admin entry that can remain in that case.
            need_prune = True

        try:
            _rmtree(wt.path)
        except OSError as err:
            click.echo(f"  ⚠️  could not fully remove {_display_path(wt.path)}: {err}")
            failed += 1
            continue

        removed += 1
        _cleanup_empty_parent(wt.path)

    if need_prune:
        subprocess.run(["git", "worktree", "prune"], cwd=repo_root, capture_output=True)

    after = _free_by_device(anchors)
    return _ReapResult(reclaimed_bytes=_reclaimed_bytes(before, after), removed=removed, failed=failed)


def _free_by_device(anchors: Sequence[Path]) -> dict[int, int]:
    """Free bytes per filesystem (keyed by device id) for the given anchor dirs.

    Keying by st_dev collapses anchors on the same filesystem and keeps separate
    volumes (e.g. the repo vs the home-dir posthog-code root) independent.
    """

    free: dict[int, int] = {}
    for anchor in anchors:
        try:
            device = anchor.stat().st_dev
            free[device] = shutil.disk_usage(anchor).free
        except OSError:
            continue
    return free


def _reclaimed_bytes(before: dict[int, int], after: dict[int, int]) -> float:
    """Total real bytes reclaimed = summed per-filesystem free-space increase.

    Returns -1.0 (unknown) if nothing could be measured. Per-device deltas are
    clamped at 0 so concurrent writes on a busy volume can't show as negative.
    """

    common = before.keys() & after.keys()
    if not common:
        return -1.0
    return float(sum(max(0, after[device] - before[device]) for device in common))


def _rmtree(path: Path) -> None:
    """Remove a directory tree, including entries inside read-only directories.

    Go creates its module cache without write permission. `shutil.rmtree` alone
    cannot delete entries from a directory that is not writable.

    Removal continues past an entry that cannot be deleted, so one stuck entry
    does not keep the rest of the tree on disk. The first such error is raised
    at the end. A path that does not exist is already removed, so it is not an
    error.
    """

    unresolved: list[BaseException] = []

    def make_parent_writable_and_retry(function: Callable[..., object], failed: str, error: BaseException) -> None:
        if isinstance(error, FileNotFoundError):
            return
        parent = Path(failed).parent
        # A parent outside `path` is not part of the tree, so its permissions stay as they are.
        if isinstance(error, PermissionError) and function in (os.unlink, os.rmdir) and parent.is_relative_to(path):
            try:
                parent.chmod(0o700)
                function(failed)
                return
            except OSError:
                pass
        unresolved.append(error)

    shutil.rmtree(path, onexc=make_parent_writable_and_retry)
    if unresolved:
        raise unresolved[0]


def _delete_paths(paths: Sequence[Path]) -> int:
    """Remove artifact directories and files; return how many could not be removed.

    Every removal outside --mode full goes through here, so the nested-repo
    guard sits here too. A folder that holds a `.git` entry at any depth may
    hold commits or edits that no other copy has, and it is kept whatever rule
    selected it.
    """

    failures = 0
    for path in paths:
        try:
            if path.is_dir() and not path.is_symlink():
                if _holds_git_entry(path):
                    click.echo(f"  ⚠️  kept {_display_path(path)} because a git repository is inside it.")
                    failures += 1
                    continue
                _rmtree(path)
            else:
                path.unlink(missing_ok=True)
        except OSError as err:
            click.echo(f"  ⚠️  could not remove {_display_path(path)}: {err}")
            failures += 1
    return failures


def _holds_git_entry(directory: Path) -> bool:
    pending = [str(directory)]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for entry in entries:
                    if entry.name == ".git":
                        return True
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(entry.path)
        except OSError:
            return True
    return False


def _cleanup_empty_parent(path: Path) -> None:
    """Remove a now-empty parent (e.g. PostHog Desktop's <id>/ after <id>/posthog)."""

    parent = path.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _ago(timestamp: float) -> str:
    if timestamp == float("inf"):
        return "unknown"
    delta = max(0.0, time.time() - timestamp)
    for unit, seconds in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= seconds:
            return f"{int(delta // seconds)}{unit}"
    return f"{int(delta)}s"
