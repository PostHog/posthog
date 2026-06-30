"""Clean up unused agent worktrees (Claude Code, Codex, PostHog Code).

These tools each create throwaway git worktrees that accumulate over time. A
single PostHog worktree carries multi-GB `node_modules`, Python venvs, and Rust
build artifacts, so stale ones are by far the largest reclaimable disk on a dev
machine. This command finds them, filters by age, and either removes the whole
worktree or just its dependencies/build artifacts (keeping the code).

The discovery roots and dependency patterns are PostHog-specific, but the age
logic and deletion modes are generic.

Safety: age is a staleness heuristic, not a "no unsaved work" guarantee — edits
made without any git operation may not move the activity signal. So `--mode full`
skips a worktree with uncommitted/untracked changes, unpushed commits, or git
state it cannot read (present-but-corrupt/locked) unless `--include-dirty` is
given. Orphaned worktrees (admin gitdir pruned) are removed by default: deleting
the directory never touches git refs, so committed work survives in the shared
repo — only uncommitted edits in an already-stale tree could be lost. `--mode
deps` only removes recreatable artifacts, so it has no such gate — it can strip
deps from a worktree that is idle by the activity signal but still has a live
dev server/build running.
"""

from __future__ import annotations

import os
import re
import time
import shutil
import subprocess
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import click
from hogli.manifest import REPO_ROOT

from .doctor import _format_size


# Roots that hold agent-created worktrees, keyed by the tool that owns them.
# Claude Code and Codex nest worktrees directly under the repo; PostHog Code
# keeps them in the home directory as <id>/posthog. Returned as (source, root).
def _worktree_roots(repo_root: Path) -> list[tuple[str, Path]]:
    return [
        ("claude", repo_root / ".claude" / "worktrees"),
        ("codex", repo_root / ".codex" / "worktrees"),
        ("posthog-code", Path.home() / ".posthog-code" / "worktrees"),
    ]


# Dependency/build-artifact directory names removed in --mode deps. Matched at
# any depth and never descended into once matched, so walking stays cheap.
DEPS_RECURSIVE_DIRS = frozenset(
    {
        "node_modules",
        "target",  # Cargo — guarded by _looks_like_cargo_target
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".parcel-cache",
        ".turbo",
    }
)

# Directories never walked into when collecting deps — either handled explicitly
# below or off-limits (git metadata).
DEPS_WALK_SKIP = frozenset({".git", ".flox", ".venv", "venv"})

# Explicit relative paths (globs allowed) removed in --mode deps. These are not
# matched recursively, so they must name their location from the worktree root.
DEPS_EXPLICIT_PATHS = (
    ".venv",
    "venv",
    ".flox/cache/venv",
    "frontend/dist",
    "frontend/.cache",
    "frontend/tmp",
    "frontend/storybook-static",
    "storybook-static",
    "playwright-report",
    "playwright/test-results",
    "test-results",
    "products/*/dist",
    "products/*/storybook-static",
)

# Leaf names of the explicit artifact paths above — pruned from os.walk so the
# walk doesn't descend their interiors before the explicit-glob pass deletes
# them wholesale.
DEPS_WALK_PRUNE_LEAVES = frozenset({"dist", ".cache", "tmp", "storybook-static", "playwright-report", "test-results"})

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

# du can hang on a stale network mount; bound it so one bad path can't stall the
# whole sizing pool.
_DU_TIMEOUT_SECONDS = 120.0


@dataclass
class Worktree:
    """A discovered agent worktree."""

    source: str
    path: Path
    registered: bool
    locked: bool
    branch: str
    last_activity: float
    size: float = 0.0
    deps_items: list[Path] = field(default_factory=list)
    deps_sizes: dict[str, float] = field(default_factory=dict)
    dirty: bool = False
    unpushed: int = 0
    detached: bool = False
    state_unknown: bool = False

    @property
    def unsafe(self) -> bool:
        """Holds (or might hold) work that a full removal would destroy.

        Includes worktrees whose git state we couldn't read — an orphaned or
        unreadable worktree might contain uncommitted work, so we fail closed
        and treat "can't verify it's clean" as unsafe rather than deleting it.
        """
        return self.dirty or self.unpushed > 0 or self.state_unknown


@click.command(
    name="worktrees:clean",
    help="Clear out unused Claude Code / Codex / PostHog Code worktrees by age",
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
    type=click.Choice(["full", "deps"], case_sensitive=False),
    default=None,
    help="Required. 'full' removes the whole worktree; 'deps' removes only deps/build artifacts, keeping the code.",
)
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=click.Choice(["claude", "codex", "posthog-code"], case_sensitive=False),
    help="Restrict to specific tool(s). Repeatable. Default: all three.",
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
    "Default: yes for --mode deps, ask for --mode full.",
)
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
def worktrees_clean(
    before: str | None,
    mode: str | None,
    sources: tuple[str, ...],
    repo: str | None,
    include_dirty: bool,
    orphans: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Find and clean up stale agent worktrees by age and deletion mode."""

    # Both selectors are mandatory — without an explicit age cutoff and mode we
    # do nothing, so an accidental bare invocation can never delete anything.
    # UsageError (exit 2) so a scripted caller can detect the misuse.
    if before is None or mode is None:
        raise click.UsageError(
            "Both --before and --mode are required.\n\n"
            "Examples:\n"
            "  hogli worktrees:clean --before 7d --mode deps     # free deps in worktrees idle >7 days\n"
            "  hogli worktrees:clean --before 2026-06-01 --mode full\n"
            "  hogli worktrees:clean --before all --mode full --dry-run\n"
            "  hogli worktrees:clean --before 30d --mode full --repo ~/Projects/other-repo"
        )

    mode = mode.lower()
    orphan_policy = _resolve_orphan_policy(orphans, mode)
    repo_root = _resolve_repo(repo)
    repo_common = _git_common_dir(repo_root)
    cutoff, cutoff_label = _parse_cutoff(before)

    selected_sources = {s.lower() for s in sources} if sources else None
    protected = _protected_paths(repo_root)

    registry = _registered_worktrees(repo_root)
    if registry is None:
        # We couldn't read git's worktree list, so we can't tell which worktrees
        # are locked. Refuse rather than risk deleting a locked worktree.
        click.echo("Could not read `git worktree list` for this repo; aborting to stay safe.")
        return

    candidates: list[Worktree] = []
    for source, root in _worktree_roots(repo_root):
        if selected_sources is not None and source not in selected_sources:
            continue
        for path in _discover_worktrees(root):
            resolved = _resolve(path)
            if resolved in protected:
                continue
            # PostHog Code worktrees live outside the repo and the home root is
            # shared across repos, so only act on worktrees owned by this repo.
            if not _belongs_to_repo(resolved, repo_root, repo_common):
                continue
            meta = registry.get(resolved)
            if meta and meta["locked"]:
                continue  # never touch a git-locked worktree
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

    if not candidates:
        click.echo(f"No agent worktrees found for {_display_path(repo_root)}.")
        return

    stale = [wt for wt in candidates if wt.last_activity < cutoff]
    click.echo(f"Found {len(candidates)} worktree(s); {len(stale)} match the filter ({cutoff_label}).\n")
    if not stale:
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
    _populate_sizes(stale, mode)

    for wt in sorted(stale, key=lambda w: w.last_activity):
        markers = _listing_markers(wt, mode)
        click.echo(
            f"  {_format_size(wt.size):>10}  {_ago(wt.last_activity):>12} ago  {markers}  {_display_path(wt.path)}"
        )

    total = sum(wt.size for wt in stale)
    action = "fully remove" if mode == "full" else "strip deps/build artifacts from"
    click.echo(
        f"\nWould {action} {len(stale)} worktree(s); estimated up to ~{_format_size(total)} "
        "(cloned/hardlinked deps free less — the actual reclaimed total is measured after deletion)."
    )

    if dry_run:
        click.echo("[DRY-RUN] Nothing deleted.")
        return

    if not yes and not click.confirm(f"\nProceed to {action} these {len(stale)} worktree(s)?", default=False):
        click.echo("Aborted.")
        return

    reclaimed, removed, failed = _execute(stale, mode, repo_root)
    if reclaimed >= 0:
        summary = f"\n✓ Done. Reclaimed ~{_format_size(reclaimed)} of disk across {removed}/{len(stale)} worktree(s)."
    else:
        summary = f"\n✓ Done. Removed {removed}/{len(stale)} worktree(s) (reclaimed space could not be measured)."
    if failed:
        summary += f" {failed} could not be fully removed (see warnings above)."
    click.echo(summary)


def _resolve_orphan_policy(explicit: str | None, mode: str) -> str:
    """Resolve --orphans, defaulting per mode: deps cleans orphans (their deps are
    just recreatable artifacts), full prompts (it deletes the working copy)."""

    if explicit is not None:
        return explicit.lower()
    return "ask" if mode == "full" else "yes"


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

    Depth 1 covers Claude/Codex (root/<name>); depth 2 covers PostHog Code
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


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(_resolve(parent))
        return True
    except ValueError:
        return False


def _belongs_to_repo(resolved_path: Path, repo_root: Path, repo_common: Path | None) -> bool:
    """Whether a worktree is owned by *repo_root*.

    Worktrees physically inside the repo always belong to it. For out-of-repo
    worktrees (PostHog Code's home root is shared across repos), confirm via the
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
    status = _git(wt.path, ["status", "--porcelain"])
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
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _state_markers(wt: Worktree) -> str:
    parts: list[str] = []
    if wt.dirty:
        parts.append("uncommitted changes")
    if wt.unpushed:
        parts.append(f"{wt.unpushed} unpushed commit(s)")
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
        if wt.unpushed:
            parts.append(f"{wt.unpushed} unpushed")
        if wt.detached:
            parts.append("detached")
        if wt.state_unknown:
            parts.append("unreadable")
    return " · ".join(parts)


def _populate_sizes(worktrees: list[Worktree], mode: str) -> None:
    """Fill in .size (and deps items/sizes for deps mode) using a thread pool."""

    def work(wt: Worktree) -> None:
        if mode == "full":
            wt.deps_sizes = _du_sizes([wt.path])
        else:
            wt.deps_items = _collect_deps_items(wt.path)
            wt.deps_sizes = _du_sizes(wt.deps_items)
        wt.size = sum(wt.deps_sizes.values())

    if not worktrees:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(worktrees))) as pool:
        list(pool.map(work, worktrees))


def _collect_deps_items(worktree: Path) -> list[Path]:
    """Find dependency/build-artifact directories inside a worktree.

    Every returned path is resolved and confirmed to stay within the worktree, so
    a symlinked component (e.g. a `frontend` symlinked to shared storage) can
    never cause deletion outside the worktree.
    """

    worktree_resolved = _resolve(worktree)
    items: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        resolved = _resolve(candidate)
        if not _is_under(resolved, worktree_resolved):
            return  # symlink/`..` escape — refuse to delete outside the worktree
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            items.append(resolved)

    for dirpath, dirnames, _ in os.walk(worktree):
        matched: list[str] = []
        for name in list(dirnames):
            if name in DEPS_RECURSIVE_DIRS:
                full = Path(dirpath) / name
                if name == "target" and not _looks_like_cargo_target(full):
                    continue
                add(full)
                matched.append(name)
        # Don't descend into matched artifacts, skip-listed dirs, or the
        # explicit-path artifact dirs (handled by the glob pass below).
        dirnames[:] = [
            d for d in dirnames if d not in matched and d not in DEPS_WALK_SKIP and d not in DEPS_WALK_PRUNE_LEAVES
        ]

    for pattern in DEPS_EXPLICIT_PATHS:
        for path in worktree.glob(pattern):
            if path.is_dir():
                add(path)

    return items


def _looks_like_cargo_target(path: Path) -> bool:
    return (path / "CACHEDIR.TAG").exists() or (path / "debug").exists() or (path / "release").exists()


def _du_sizes(paths: Sequence[Path]) -> dict[str, float]:
    """On-disk size in bytes per path via a single `du -sk`.

    Keyed by the string path passed to `du` (which echoes it back). Parses
    whatever du printed regardless of exit code, so one unreadable path doesn't
    zero the whole batch.
    """

    existing = [str(p) for p in paths if p.exists()]
    if not existing:
        return {}
    try:
        result = subprocess.run(
            ["du", "-sk", *existing],
            capture_output=True,
            text=True,
            timeout=_DU_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return {}

    sizes: dict[str, float] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        size_kb, path_str = parts[0].strip(), parts[1].strip()
        if size_kb.isdigit():
            sizes[path_str] = int(size_kb) * 1024.0
    return sizes


def _execute(worktrees: list[Worktree], mode: str, repo_root: Path) -> tuple[float, int, int]:
    """Delete the selected worktrees (or their deps).

    Returns (real_bytes_reclaimed, worktrees_removed, worktrees_failed). The
    reclaimed figure is measured from actual filesystem free space before/after,
    so it reflects what was genuinely freed — hardlinked (pnpm store) and
    copy-on-write-cloned (APFS) blocks that are shared elsewhere don't count,
    unlike the du-based pre-delete estimate. Falls back to -1.0 if free space
    couldn't be measured.
    """

    # Anchor on each target's parent (which survives the deletion) so disk_usage
    # has a readable path on the same filesystem before and after.
    anchors = [wt.path.parent for wt in worktrees]
    before = _free_by_device(anchors)

    removed = 0
    failed = 0
    need_prune = False

    for wt in worktrees:
        if mode == "deps":
            _, failures = _delete_paths(wt.deps_items, wt.deps_sizes)
            if failures:
                failed += 1
            else:
                removed += 1
            continue

        if wt.registered:
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", "--", str(wt.path)],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip()
                click.echo(f"  ⚠️  git worktree remove failed for {_display_path(wt.path)}: {stderr}")
                shutil.rmtree(wt.path, ignore_errors=True)
            # Either path may have removed it; prune any dangling admin entry.
            need_prune = True
        else:
            shutil.rmtree(wt.path, ignore_errors=True)

        if wt.path.exists():
            click.echo(f"  ⚠️  could not fully remove {_display_path(wt.path)}")
            failed += 1
        else:
            removed += 1
            _cleanup_empty_parent(wt.path)

    if need_prune:
        subprocess.run(["git", "worktree", "prune"], cwd=repo_root, capture_output=True)

    after = _free_by_device(anchors)
    return _reclaimed_bytes(before, after), removed, failed


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


def _delete_paths(paths: Sequence[Path], sizes: dict[str, float]) -> tuple[float, int]:
    """Remove deps directories; return (bytes actually freed, paths that failed)."""

    freed = 0.0
    failures = 0
    for path in paths:
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            continue  # already gone — not a failure
        except OSError as err:
            click.echo(f"  ⚠️  could not remove {_display_path(path)}: {err}")
            failures += 1
            continue
        freed += sizes.get(str(path), 0.0)
    return freed, failures


def _cleanup_empty_parent(path: Path) -> None:
    """Remove a now-empty parent (e.g. PostHog Code's <id>/ after <id>/posthog)."""

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
