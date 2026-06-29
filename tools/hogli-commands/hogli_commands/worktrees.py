"""Clean up unused agent worktrees (Claude Code, Codex, PostHog Code).

These tools each create throwaway git worktrees that accumulate over time. A
single PostHog worktree carries multi-GB `node_modules`, Python venvs, and Rust
build artifacts, so stale ones are by far the largest reclaimable disk on a dev
machine. This command finds them, filters by age, and either removes the whole
worktree or just its dependencies/build artifacts (keeping the code).

The discovery roots and dependency patterns are PostHog-specific, but the age
logic and deletion modes are generic.
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

_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


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


@click.command(
    name="worktrees:clean",
    help="Clear out unused Claude Code / Codex / PostHog Code worktrees",
)
@click.option(
    "--before",
    default=None,
    metavar="DATE|INTERVAL|all",
    help="Cutoff: a date (2026-06-01), an interval older-than (3h, 7d, 2w), or 'all' for everything.",
)
@click.option(
    "--mode",
    type=click.Choice(["full", "deps"], case_sensitive=False),
    default=None,
    help="'full' removes the whole worktree; 'deps' removes only deps/build artifacts, keeping the code.",
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
@click.option("--dry-run", is_flag=True, help="Show what would be removed without deleting.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
def worktrees_clean(
    before: str | None,
    mode: str | None,
    sources: tuple[str, ...],
    repo: str | None,
    dry_run: bool,
    yes: bool,
) -> None:
    """Find and clean up stale agent worktrees by age and deletion mode."""

    # Both selectors are mandatory — without an explicit age cutoff and mode we
    # do nothing, so an accidental bare invocation can never delete anything.
    if before is None or mode is None:
        click.echo("Both --before and --mode are required; nothing to do.\n")
        click.echo("Examples:")
        click.echo("  hogli worktrees:clean --before 7d --mode deps     # free deps in worktrees idle >7 days")
        click.echo("  hogli worktrees:clean --before 2026-06-01 --mode full")
        click.echo("  hogli worktrees:clean --before all --mode full --dry-run")
        click.echo("  hogli worktrees:clean --before 30d --mode full --repo ~/Projects/other-repo")
        return

    mode = mode.lower()
    repo_root = _resolve_repo(repo)
    cutoff, cutoff_label = _parse_cutoff(before)

    selected_sources = {s.lower() for s in sources} if sources else None
    protected = _protected_paths(repo_root)

    candidates: list[Worktree] = []
    registry = _registered_worktrees(repo_root)
    for source, root in _worktree_roots(repo_root):
        if selected_sources is not None and source not in selected_sources:
            continue
        for path in _discover_worktrees(root):
            resolved = _resolve(path)
            if resolved in protected:
                continue
            # PostHog Code worktrees live outside the repo and the home root is
            # shared across repos, so only act on worktrees owned by this repo.
            if not _belongs_to_repo(resolved, repo_root):
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
    click.echo(f"Found {len(candidates)} worktree(s); {len(stale)} match {cutoff_label}.\n")
    if not stale:
        return

    # Size only the worktrees we're actually going to act on.
    _populate_sizes(stale, mode)

    for wt in sorted(stale, key=lambda w: w.last_activity):
        age = _ago(wt.last_activity)
        flags = "" if wt.registered else " [orphaned]"
        click.echo(f"  {_format_size(wt.size):>10}  {age:>12} ago  {wt.source}{flags}  {_display_path(wt.path)}")

    total = sum(wt.size for wt in stale)
    action = "remove entirely" if mode == "full" else "strip deps/build artifacts from"
    click.echo(f"\nWould {action} {len(stale)} worktree(s), reclaiming ~{_format_size(total)}.")

    if dry_run:
        click.echo("[DRY-RUN] Nothing deleted.")
        return

    if not yes and not click.confirm(f"\nProceed to {action} these {len(stale)} worktree(s)?", default=False):
        click.echo("Aborted.")
        return

    freed = _execute(stale, mode, repo_root)
    click.echo(f"\n✓ Done. Reclaimed ~{_format_size(freed)}.")


def _resolve_repo(repo: str | None) -> Path:
    """Resolve --repo (or the current dir) to its git top-level directory."""

    if repo is None:
        return _resolve(REPO_ROOT)
    base = Path(repo).expanduser()
    if not base.exists():
        raise click.BadParameter(f"{repo!r} does not exist.")
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=base,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise click.BadParameter(f"{repo!r} is not inside a git repository.") from None
    return _resolve(Path(top))


def _parse_cutoff(value: str) -> tuple[float, str]:
    """Parse --before into (cutoff_epoch, human_label). Raises click.BadParameter on garbage."""

    raw = value.strip()
    lowered = raw.lower()
    if lowered == "all":
        return float("inf"), "all worktrees (all time)"

    interval = re.fullmatch(r"(\d+)([smhdw])", lowered)
    if interval:
        amount = int(interval.group(1))
        seconds = amount * _INTERVAL_UNITS[interval.group(2)]
        return time.time() - seconds, f"idle older than {amount}{interval.group(2)}"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as err:
        raise click.BadParameter(f"{value!r} is not a date (YYYY-MM-DD), an interval (3h, 7d, 2w), or 'all'.") from err
    return parsed.timestamp(), f"last active before {parsed.date()}"


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


def _registered_worktrees(repo_root: Path) -> dict[Path, dict]:
    """Map resolved worktree path -> {locked, branch} from `git worktree list`."""

    try:
        out = subprocess.check_output(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}

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
            current["branch"] = line[len("branch ") :].replace("refs/heads/", "")
        elif line == "detached":
            current["branch"] = "(detached)"
        elif line.startswith("locked") or line == "locked":
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


def _belongs_to_repo(resolved_path: Path, repo_root: Path) -> bool:
    """Whether a worktree is owned by *repo_root*.

    Worktrees physically inside the repo always belong to it. For out-of-repo
    worktrees (PostHog Code's home root is shared across repos), confirm via the
    gitdir's commondir pointing back at this repo's common git directory. A
    dangling pointer we can't attribute is treated as not ours, so we never
    delete another repo's worktree.
    """

    if _is_under(resolved_path, repo_root):
        return True
    gitdir = _gitdir_for(resolved_path)
    if gitdir is None:
        return False
    common = _common_git_dir(gitdir)
    return common is not None and common == _resolve(repo_root / ".git")


def _common_git_dir(gitdir: Path) -> Path | None:
    """Resolve a per-worktree gitdir to its shared common git dir via commondir."""

    try:
        rel = (gitdir / "commondir").read_text().strip()
    except OSError:
        return None
    return _resolve(gitdir / rel)


def _last_activity(path: Path) -> float:
    """Most recent activity signal for a worktree (max of all available signals).

    Combines git activity (mtimes inside the per-worktree gitdir: HEAD, index,
    logs/HEAD, FETCH_HEAD, ...), the Claude Code session transcript mtime if one
    exists for this path, and the worktree directory mtime as a fallback.
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

    return max(times) if times else 0.0


def _gitdir_for(path: Path) -> Path | None:
    """Resolve a worktree's gitdir from its `.git` pointer file (or dir)."""

    dot_git = path / ".git"
    try:
        if dot_git.is_dir():
            return dot_git
        content = dot_git.read_text().strip()
    except OSError:
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
    a dash. exists() is case-insensitive on macOS, so the cased path is fine.
    """

    encoded = re.sub(r"[^a-zA-Z0-9]", "-", str(_resolve(path)))
    project_dir = Path.home() / ".claude" / "projects" / encoded
    if not project_dir.is_dir():
        return None
    mtimes = [t.stat().st_mtime for t in project_dir.glob("*.jsonl") if t.is_file()]
    return max(mtimes) if mtimes else None


def _populate_sizes(worktrees: list[Worktree], mode: str) -> None:
    """Fill in .size (and .deps_items for deps mode) using a thread pool."""

    def work(wt: Worktree) -> None:
        if mode == "full":
            wt.size = _du_bytes([wt.path])
        else:
            wt.deps_items = _collect_deps_items(wt.path)
            wt.size = _du_bytes(wt.deps_items) if wt.deps_items else 0.0

    if not worktrees:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(worktrees))) as pool:
        list(pool.map(work, worktrees))


def _collect_deps_items(worktree: Path) -> list[Path]:
    """Find dependency/build-artifact directories inside a worktree."""

    items: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        resolved = _resolve(candidate)
        if resolved not in seen and candidate.exists():
            seen.add(resolved)
            items.append(candidate)

    for dirpath, dirnames, _ in os.walk(worktree):
        matched: list[str] = []
        for name in list(dirnames):
            if name in DEPS_RECURSIVE_DIRS:
                full = Path(dirpath) / name
                if name == "target" and not _looks_like_cargo_target(full):
                    continue
                add(full)
                matched.append(name)
        # Don't descend into matched artifacts or skip-listed dirs.
        dirnames[:] = [d for d in dirnames if d not in matched and d not in DEPS_WALK_SKIP]

    for pattern in DEPS_EXPLICIT_PATHS:
        for path in worktree.glob(pattern):
            if path.is_dir():
                add(path)

    return items


def _looks_like_cargo_target(path: Path) -> bool:
    return (path / "CACHEDIR.TAG").exists() or (path / "debug").exists() or (path / "release").exists()


def _du_bytes(paths: Sequence[Path]) -> float:
    """Total on-disk size of *paths* in bytes via `du -sk` (one subprocess)."""

    existing = [str(p) for p in paths if p.exists()]
    if not existing:
        return 0.0
    try:
        out = subprocess.check_output(
            ["du", "-sk", *existing],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return 0.0
    total_kb = 0
    for line in out.splitlines():
        field_kb = line.split("\t", 1)[0].strip() or line.split()[0]
        if field_kb.isdigit():
            total_kb += int(field_kb)
    return total_kb * 1024.0


def _execute(worktrees: list[Worktree], mode: str, repo_root: Path) -> float:
    """Delete the selected worktrees (or their deps) and return bytes freed."""

    freed = 0.0
    pruned_git = False
    for wt in worktrees:
        if mode == "deps":
            freed += _delete_paths(wt.deps_items, wt.size)
            continue

        removed_via_git = False
        if wt.registered:
            result = subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt.path)],
                cwd=repo_root,
                capture_output=True,
                text=True,
            )
            removed_via_git = result.returncode == 0
            pruned_git = pruned_git or removed_via_git
        if not removed_via_git:
            shutil.rmtree(wt.path, ignore_errors=True)
        freed += wt.size
        _cleanup_empty_parent(wt.path)

    if pruned_git:
        subprocess.run(["git", "worktree", "prune"], cwd=repo_root, capture_output=True)
    return freed


def _delete_paths(paths: Sequence[Path], measured: float) -> float:
    """Remove deps directories; return the measured size if anything was removed."""

    removed_any = False
    for path in paths:
        try:
            shutil.rmtree(path)
            removed_any = True
        except FileNotFoundError:
            continue
        except OSError:
            continue
    return measured if removed_any else 0.0


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
    delta = max(0.0, time.time() - timestamp)
    for unit, seconds in (("w", 604800), ("d", 86400), ("h", 3600), ("m", 60)):
        if delta >= seconds:
            return f"{int(delta // seconds)}{unit}"
    return f"{int(delta)}s"
