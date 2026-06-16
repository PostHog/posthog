from __future__ import annotations

import os
import re
import sys
import enum
import time
import shutil
import signal
import hashlib
import platform
import importlib
import subprocess
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import yaml
import click
from hogli.manifest import REPO_ROOT, get_manifest

from . import hints

MAX_SAMPLE_PATHS = 8
PYTHON_CACHE_PATTERNS = ("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache")
NODE_ARTIFACT_PATTERNS = (
    ".parcel-cache",
    ".eslintcache",
    ".turbo",
    ".yalc",
    ".typegen",
    "pnpm-error.log",
    "pnpm-debug.log",
    "frontend/.cache",
    "frontend/tmp",
    "frontend/dist",
    "frontend/storybook-static",
    "frontend/@posthog/apps-common/dist",
    "common/storybook/dist",
    "common/tailwind/dist",
    "common/plugin_transpiler/dist",
    "common/hogvm/typescript/.parcel-cache",
    "common/hogvm/typescript/dist",
    "nodejs/dist",
    "storybook-static",
    "playwright-report",
    "playwright/playwright-report",
    "playwright/test-results",
    "test-results",
    "frontend/__snapshots__/__diff_output__",
    "frontend/__snapshots__/__failures__",
    "products/*/dist",
    "products/*/storybook-static",
)


@dataclass
class CleanupItem:
    """Single file or directory slated for cleanup."""

    path: Path
    size: float
    is_dir: bool


@dataclass
class CleanupEstimate:
    """Data describing what a cleanup category would remove."""

    total_size: float
    items: list[CleanupItem] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    available: bool = True


@dataclass
class CleanupStats:
    """Result of executing a cleanup action."""

    freed: float = 0.0
    deleted_anything: bool = False


@dataclass
class CleanupCategory:
    """Metadata and handlers for a disk cleanup category."""

    id: str
    title: str
    description: Sequence[str]
    estimate: Callable[[Path], CleanupEstimate]
    cleanup: Callable[[CleanupEstimate, Path], CleanupStats]
    confirmation_prompt: str
    default_confirm: bool = True
    include_in_total: bool = True
    skip_if_empty: bool = True
    dry_run_message: str | None = None
    post_cleanup_message: str | None = None


@dataclass
class CleanupResult:
    """Outcome of running a cleanup category (used for the summary)."""

    freed: float = 0.0
    ran_cleanup: bool = False
    deleted_anything: bool = False


@click.command(
    name="doctor:disk",
    help="Interactive disk space cleanup for common PostHog dev bloat",
)
@click.option("--dry-run", is_flag=True, help="Show what would be cleaned without deleting")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm all cleanup operations")
@click.option(
    "--area",
    multiple=True,
    type=click.Choice(
        ["flox-logs", "docker", "python", "dagster", "node-artifacts", "rust", "pnpm-store", "git"],
        case_sensitive=False,
    ),
    help="Specific cleanup area(s) to run. Can be specified multiple times. Without this, all areas run.",
)
def doctor_disk(
    dry_run: bool,
    yes: bool,
    area: tuple[str, ...],
) -> None:
    """Clean up disk space by pruning caches, build outputs, and containers.

    This command is tailored to the technologies used in the repository:
    - Flox environments (Python dependencies)
    - Docker Compose services
    - Django + pytest + mypy/ruff caches
    - Dagster background job storage
    - pnpm/Vite/Tailwind/Storybook/Playwright build artifacts
    - Rust workspaces built with Cargo
    - pnpm-managed node_modules across the workspace

    By default, runs all cleanup categories interactively. Use flags to target
    specific categories. Use --dry-run to preview what would be removed and
    --yes to skip prompts.
    """

    click.echo("🔍 PostHog Disk Space Cleanup\n")

    if dry_run:
        click.echo("🚀 Running in DRY-RUN mode - no files will be deleted\n")

    all_categories: list[CleanupCategory] = [
        CleanupCategory(
            id="flox_logs",
            title="📁 Flox logs (.flox/log)",
            description=[
                "Remove Flox CLI logs older than 7 days from the dev environment manager.",
                "These logs can grow to 32GB+ after repeated 'flox' operations.",
            ],
            estimate=_estimate_flox_logs,
            cleanup=_cleanup_flox_logs,
            confirmation_prompt="Clean up Flox logs older than 7 days?",
            dry_run_message="Would run: find .flox/log -name '*.log' -mtime +7 -delete",
        ),
        CleanupCategory(
            id="docker",
            title="🐳 Docker system (images, containers, volumes)",
            description=[
                "Runs 'docker system prune -a --volumes' to reclaim unused Docker resources.",
                "PostHog's docker-compose stacks rely on Docker heavily during development.",
            ],
            estimate=_estimate_docker_usage,
            cleanup=_cleanup_docker,
            confirmation_prompt="Clean up Docker system (prune unused resources)?",
            include_in_total=False,
            skip_if_empty=False,
            dry_run_message="Would run: docker system prune -a --volumes -f",
        ),
        CleanupCategory(
            id="python",
            title="🐍 Python caches (__pycache__, .mypy_cache, .pytest_cache, .ruff_cache)",
            description=[
                "Removes bytecode and analysis caches created by Django, pytest, mypy, and ruff.",
            ],
            estimate=_estimate_python_caches,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up Python caches?",
        ),
        CleanupCategory(
            id="dagster",
            title="🔧 Dagster storage (runs older than 7 days)",
            description=[
                "Dagster jobs store logs in .dagster_home; old run data can accumulate quickly.",
            ],
            estimate=_estimate_dagster_storage,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up old Dagster run storage?",
        ),
        CleanupCategory(
            id="node_artifacts",
            title="📦 JS/TS build caches (pnpm, Vite, Tailwind, Storybook, Playwright)",
            description=[
                "Cleans build outputs and caches listed in .gitignore for the pnpm workspace.",
            ],
            estimate=_estimate_node_artifacts,
            cleanup=_cleanup_items,
            confirmation_prompt="Clean up JavaScript build caches and artifacts?",
        ),
        CleanupCategory(
            id="rust",
            title="🦀 Rust Cargo targets",
            description=[
                "Runs 'cargo clean' in all Rust workspaces to remove build artifacts.",
                "Feature flag debug builds can accumulate ~400MB each.",
            ],
            estimate=_estimate_rust_targets,
            cleanup=_cleanup_rust,
            confirmation_prompt="Clean up Rust target directories?",
            include_in_total=False,
            skip_if_empty=False,
            dry_run_message="Would run: cargo clean in all Rust workspaces",
        ),
        CleanupCategory(
            id="pnpm_store",
            title="📦 pnpm store prune",
            description=[
                "Removes unreferenced packages from the global pnpm store.",
                "Safe alternative to deleting node_modules - no reinstall needed.",
            ],
            estimate=_estimate_pnpm_store,
            cleanup=_cleanup_pnpm_store,
            confirmation_prompt="Prune unused packages from pnpm store?",
            include_in_total=False,
            skip_if_empty=False,
            dry_run_message="Would run: pnpm store prune",
        ),
        CleanupCategory(
            id="git",
            title="🧹 Git repository (.git)",
            description=[
                "Prunes stale remote branches, expires reflogs, and repacks objects.",
                "Combines: git remote prune + reflog expire + gc --aggressive.",
                "Can reclaim 25-40% of .git size (1-1.5GB in large repos).",
            ],
            estimate=_estimate_git,
            cleanup=_cleanup_git,
            confirmation_prompt="Run Git cleanup (prune + gc)?",
            include_in_total=False,
            skip_if_empty=False,
            dry_run_message="Would run: git remote prune + reflog expire (30 days) + gc --aggressive",
        ),
    ]

    # Filter categories based on --area flag
    if area:
        # Convert area names (with hyphens) to category IDs (with underscores)
        enabled_ids = {area_name.replace("-", "_") for area_name in area}
        categories = [cat for cat in all_categories if cat.id in enabled_ids]
    else:
        categories = all_categories

    results: list[CleanupResult] = []
    for category in categories:
        results.append(_run_category(category, REPO_ROOT, dry_run, yes, silent=False))

    total_freed = sum(result.freed for result in results)
    non_counted = [
        category.title
        for category, result in zip(categories, results)
        if not category.include_in_total and result.ran_cleanup
    ]

    click.echo("\n" + "━" * 60)
    click.echo("\n✨ Summary")
    if dry_run:
        click.echo("   [DRY-RUN] No files were actually deleted.")
    else:
        if total_freed > 0:
            click.echo(f"   Total space freed: {_format_size(total_freed)}")
        elif any(result.ran_cleanup for result in results):
            click.echo("   Cleanup completed but no measurable files were removed.")
        else:
            click.echo("   No cleanup actions were run.")

        if non_counted:
            titles = ", ".join(non_counted)
            click.echo(f"   Note: {titles} cleanup is not included in the total freed space.")

    if not dry_run:
        hints.record_check_run("doctor:disk")


def _run_category(
    category: CleanupCategory,
    repo_root: Path,
    dry_run: bool,
    auto_confirm: bool,
    silent: bool = False,
) -> CleanupResult:
    """Execute a cleanup category interactively and return the outcome."""

    if not silent:
        click.echo("\n" + "━" * 60)
        click.echo(f"\n{category.title}")

        for line in category.description:
            click.echo(f"   {line}")

    estimate = category.estimate(repo_root)

    if not silent:
        for detail in estimate.details:
            click.echo(detail)

    if not estimate.available:
        return CleanupResult()

    if estimate.total_size <= 0 and category.skip_if_empty and not estimate.items:
        if not silent and not estimate.details:
            click.echo("   ✓ Already clean (0 bytes)")
        return CleanupResult()

    if not silent and estimate.total_size > 0:
        click.echo(f"   Estimated size: {_format_size(estimate.total_size)}")

    prompt = (
        category.confirmation_prompt
        if category.confirmation_prompt.endswith("?")
        else f"{category.confirmation_prompt}?"
    )

    # In dry-run mode, always proceed without prompting
    if dry_run or auto_confirm or (not silent and click.confirm(f"\n   {prompt}", default=category.default_confirm)):
        if dry_run:
            if not silent:
                if category.dry_run_message:
                    click.echo(f"   [DRY-RUN] {category.dry_run_message}")
                if category.include_in_total and estimate.total_size > 0:
                    click.echo(f"   [DRY-RUN] Would clean {_format_size(estimate.total_size)}")
                elif not category.include_in_total:
                    click.echo("   [DRY-RUN] Would execute cleanup command.")
            return CleanupResult()

        stats = category.cleanup(estimate, repo_root)

        if not silent:
            if category.include_in_total:
                if stats.freed > 0:
                    click.echo(f"   ✓ Cleaned {_format_size(stats.freed)}")
                else:
                    click.echo("   ✓ Cleanup completed (no files removed)")

            if category.post_cleanup_message:
                click.echo(category.post_cleanup_message)

        return CleanupResult(
            freed=stats.freed if category.include_in_total else 0.0,
            ran_cleanup=True,
            deleted_anything=stats.deleted_anything,
        )

    if not silent:
        click.echo("   ⏭️  Skipped")
    return CleanupResult()


def _estimate_flox_logs(repo_root: Path) -> CleanupEstimate:
    """Check Flox log directory - cleanup happens via find command."""

    flox_log_dir = repo_root / ".flox" / "log"
    if not flox_log_dir.exists():
        return CleanupEstimate(
            total_size=0.0,
            details=["   Flox log directory not found."],
            items=[],
        )

    # Just check if directory exists and has logs - don't calculate sizes
    # Cleanup is done via find command for simplicity
    log_count = len(list(flox_log_dir.glob("*.log")))

    details = [
        "   Runs: find .flox/log -name '*.log' -mtime +7 -delete",
        f"   Found {log_count} log file(s) in directory.",
    ]

    return CleanupEstimate(total_size=0.0, items=[], details=details)


def _estimate_python_caches(repo_root: Path) -> CleanupEstimate:
    """Identify Python cache directories such as __pycache__ and mypy caches."""

    items = list(_collect_python_cache_dirs(repo_root))
    total = sum(item.size for item in items)

    if items:
        details = [f"   Found {len(items)} Python cache director{'ies' if len(items) != 1 else 'y'}."]
        details.extend(_describe_items(items, repo_root, "   Sample cache locations:"))
    else:
        details = ["   No Python cache directories detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_dagster_storage(repo_root: Path) -> CleanupEstimate:
    """Collect Dagster storage files older than seven days."""

    storage_dir = repo_root / ".dagster_home" / "storage"
    if not storage_dir.exists():
        return CleanupEstimate(
            total_size=0.0,
            details=["   Dagster storage directory not found."],
            items=[],
        )

    items = list(_collect_old_dagster_files(storage_dir))
    total = sum(item.size for item in items)

    details = [
        "   Removes execution logs older than 7 days to keep Dagster lean.",
    ]
    if items:
        details.append(f"   Found {len(items)} file(s) older than 7 days in {storage_dir.relative_to(repo_root)}.")
        details.extend(_describe_items(items, repo_root, "   Sample files:"))
    else:
        details.append("   No Dagster files older than 7 days detected.")

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_node_artifacts(repo_root: Path) -> CleanupEstimate:
    """Collect Node.js/TypeScript build caches and artifacts listed in .gitignore."""

    items = _collect_paths_from_patterns(repo_root, NODE_ARTIFACT_PATTERNS)
    total = sum(item.size for item in items)

    if items:
        details = [
            "   Cleans pnpm/Vite/Tailwind/Storybook/Playwright caches and build outputs.",
            f"   Found {len(items)} path(s) matching known artifact locations.",
        ]
        details.extend(_describe_items(items, repo_root, "   Sample paths:"))
    else:
        details = ["   No JavaScript build caches detected."]

    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_rust_targets(repo_root: Path) -> CleanupEstimate:
    """Identify Cargo workspaces and their target directories."""

    # Check if cargo is available
    try:
        subprocess.run(["cargo", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return CleanupEstimate(
            total_size=0.0,
            items=[],
            details=["   Cargo not available; skipping."],
            available=False,
        )

    # Find all Cargo workspace roots (directories with Cargo.toml that have workspaces or are standalone)
    workspace_roots = _find_cargo_workspaces(repo_root)

    if not workspace_roots:
        return CleanupEstimate(
            total_size=0.0,
            items=[],
            details=["   No Cargo workspaces detected."],
        )

    # Collect target directories to estimate size
    items = _collect_rust_target_dirs(repo_root)
    total = sum(item.size for item in items)

    details = [
        f"   Found {len(workspace_roots)} Cargo workspace(s) to clean.",
    ]

    if items:
        details.append(f"   Total target directory size: {_format_size(total)}")
        details.extend(_describe_items(items, repo_root, "   Target directories:"))

    # Store workspace roots in items for cleanup function
    return CleanupEstimate(total_size=total, items=items, details=details)


def _estimate_pnpm_store(repo_root: Path) -> CleanupEstimate:
    """Check pnpm store - cleanup happens via pnpm store prune."""

    try:
        subprocess.run(["pnpm", "--version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return CleanupEstimate(
            total_size=0.0,
            items=[],
            details=["   pnpm not available; skipping."],
            available=False,
        )

    details = [
        "   Runs: pnpm store prune",
        "   Removes unreferenced packages from global store.",
        "   Safe operation - no reinstall needed.",
    ]

    return CleanupEstimate(total_size=0.0, items=[], details=details)


def _estimate_git(repo_root: Path) -> CleanupEstimate:
    """Check .git directory size and estimate reclaimable space."""

    # Handle git worktrees by finding the main .git directory
    git_dir = repo_root / ".git"
    if git_dir.is_file():
        # It's a worktree, read the actual git dir path
        try:
            gitdir_content = git_dir.read_text().strip()
            if gitdir_content.startswith("gitdir: "):
                actual_git_path = Path(gitdir_content[8:])
                # Go up to the main .git directory (worktrees/xxx -> .git)
                git_dir = actual_git_path.parent.parent
        except (OSError, ValueError):
            # If reading or parsing .git file fails, fallback to default .git directory
            pass

    if not git_dir.exists() or not git_dir.is_dir():
        return CleanupEstimate(
            total_size=0.0,
            details=["   No .git directory found."],
            items=[],
            available=False,
        )

    # Get current size
    git_size, _ = _get_dir_size(git_dir)

    # Count packs and get object stats
    pack_count = (
        len(list((git_dir / "objects" / "pack").glob("*.pack"))) if (git_dir / "objects" / "pack").exists() else 0
    )

    details = [
        f"   Current .git size: {_format_size(git_size)}",
        f"   Pack files: {pack_count}",
        "   Estimated reclaimable: ~30% (25-40% typical)",
        "   Operations: remote prune + reflog expire + gc --aggressive",
    ]

    return CleanupEstimate(total_size=0.0, items=[], details=details)


def _estimate_docker_usage(repo_root: Path) -> CleanupEstimate:
    """Summarise Docker disk usage via `docker system df`. Repo root unused (compat)."""

    try:
        subprocess.run(["docker", "info"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return CleanupEstimate(
            total_size=0.0,
            items=[],
            details=["   Docker not available or not running; skipping."],
            available=False,
        )

    df_result = subprocess.run(["docker", "system", "df"], capture_output=True, text=True, check=False)

    details = ["   Current Docker disk usage:"]
    if df_result.returncode == 0 and df_result.stdout.strip():
        details.extend([f"     {line}" for line in df_result.stdout.strip().splitlines()])
    else:
        details.append("     (Unable to retrieve docker system df output)")

    details.append("   Command to run: docker system prune -a --volumes -f")

    return CleanupEstimate(total_size=0.0, items=[], details=details)


def _cleanup_items(estimate: CleanupEstimate, _: Path) -> CleanupStats:
    """Delete all items in the estimate and report freed bytes."""

    freed = _delete_items(estimate.items)
    return CleanupStats(freed=freed, deleted_anything=freed > 0)


def _cleanup_flox_logs(_: CleanupEstimate, repo_root: Path) -> CleanupStats:
    """Execute find command to clean up old Flox logs."""

    flox_log_dir = repo_root / ".flox" / "log"
    if not flox_log_dir.exists():
        return CleanupStats(deleted_anything=False)

    result = subprocess.run(
        ["find", str(flox_log_dir), "-name", "*.log", "-type", "f", "-mtime", "+7", "-delete"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return CleanupStats(deleted_anything=True)

    return CleanupStats(deleted_anything=False)


def _cleanup_git(_: CleanupEstimate, repo_root: Path) -> CleanupStats:
    """Execute git cleanup: prune remotes, expire reflogs, and run gc."""

    click.echo()
    success = True

    # Step 1: Prune stale remote branches
    click.echo("   Running git remote prune origin...")
    result = subprocess.run(["git", "remote", "prune", "origin"], cwd=repo_root, check=False)
    if result.returncode != 0:
        success = False

    # Step 2: Expire old reflogs (keep 30 days for safety)
    click.echo("   Expiring old reflogs...")
    result = subprocess.run(["git", "reflog", "expire", "--expire=30.days.ago", "--all"], cwd=repo_root, check=False)
    if result.returncode != 0:
        success = False

    # Step 3: Run gc --aggressive (this can take 1-2 minutes)
    # Git will show its own progress output
    # Note: omit --prune=now to use git's safe 2-week default
    click.echo("   Running git gc --aggressive (may take 1-2 minutes)...")
    result = subprocess.run(["git", "gc", "--aggressive"], cwd=repo_root, check=False)
    if result.returncode != 0:
        success = False

    if success:
        click.echo("   ✓ Git cleanup completed")
    else:
        click.echo("   ⚠️  Git cleanup completed with some errors")

    return CleanupStats(deleted_anything=success)


def _cleanup_pnpm_store(_: CleanupEstimate, __: Path) -> CleanupStats:
    """Execute pnpm store prune command."""

    click.echo()
    result = subprocess.run(["pnpm", "store", "prune"], check=False)
    if result.returncode == 0:
        click.echo("   ✓ pnpm store pruned")
        return CleanupStats(deleted_anything=True)

    click.echo("   ⚠️  pnpm store prune failed")
    return CleanupStats(deleted_anything=False)


def _cleanup_docker(_: CleanupEstimate, __: Path) -> CleanupStats:
    """Execute docker system prune command."""

    click.echo()
    result = subprocess.run(["docker", "system", "prune", "-a", "--volumes", "-f"], check=False)
    if result.returncode == 0:
        click.echo("   ✓ Docker cleanup completed")
        return CleanupStats(deleted_anything=True)

    click.echo("   ⚠️  Docker cleanup failed")
    return CleanupStats(deleted_anything=False)


def _cleanup_rust(_: CleanupEstimate, repo_root: Path) -> CleanupStats:
    """Execute cargo clean in all Rust workspaces."""

    workspace_roots = _find_cargo_workspaces(repo_root)

    if not workspace_roots:
        return CleanupStats(deleted_anything=False)

    click.echo()
    success = True
    cleaned_any = False

    for workspace in workspace_roots:
        try:
            relative = workspace.relative_to(repo_root)
        except ValueError:
            relative = workspace

        click.echo(f"   Running cargo clean in {relative}...")
        result = subprocess.run(["cargo", "clean"], cwd=workspace, capture_output=True, check=False)

        if result.returncode == 0:
            cleaned_any = True
        else:
            success = False
            click.echo(f"   ⚠️  Failed to clean {relative}")

    if success and cleaned_any:
        click.echo("   ✓ Cargo cleanup completed")
    elif cleaned_any:
        click.echo("   ✓ Cargo cleanup completed with some errors")
    else:
        click.echo("   ⚠️  Cargo cleanup failed")

    return CleanupStats(deleted_anything=cleaned_any)


def _collect_python_cache_dirs(repo_root: Path) -> Iterable[CleanupItem]:
    """Yield CleanupItem objects for Python cache directories."""

    seen: set[Path] = set()
    for pattern in PYTHON_CACHE_PATTERNS:
        for cache_dir in repo_root.glob(f"**/{pattern}"):
            if any(part in {".git", "node_modules"} for part in cache_dir.parts):
                continue
            try:
                resolved = cache_dir.resolve()
            except (FileNotFoundError, PermissionError, RuntimeError):
                continue
            if resolved in seen or not cache_dir.is_dir():
                continue
            size, _ = _get_dir_size(cache_dir)
            if size <= 0:
                continue
            seen.add(resolved)
            yield CleanupItem(cache_dir, size, is_dir=True)


def _collect_old_dagster_files(storage_dir: Path) -> Iterable[CleanupItem]:
    """Yield Dagster files older than seven days."""

    cutoff = time.time() - (7 * 24 * 60 * 60)
    for item in storage_dir.rglob("*"):
        if not item.is_file():
            continue
        try:
            stat = item.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if stat.st_mtime < cutoff and stat.st_size > 0:
            yield CleanupItem(item, stat.st_size, is_dir=False)


def _collect_paths_from_patterns(repo_root: Path, patterns: Sequence[str]) -> list[CleanupItem]:
    """Collect files/directories that match glob patterns relative to repo root."""

    items: list[CleanupItem] = []
    seen: set[Path] = set()

    for pattern in patterns:
        for path in repo_root.glob(pattern):
            try:
                resolved = path.resolve()
            except (FileNotFoundError, PermissionError, RuntimeError):
                continue
            if resolved in seen:
                continue
            seen.add(resolved)

            if path.is_dir():
                size, _ = _get_dir_size(path)
                if size <= 0:
                    continue
                items.append(CleanupItem(path, size, is_dir=True))
            else:
                try:
                    size = path.stat().st_size
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                if size <= 0:
                    continue
                items.append(CleanupItem(path, size, is_dir=False))

    return items


def _collect_rust_target_dirs(repo_root: Path) -> list[CleanupItem]:
    """Collect Cargo target directories anywhere in the repository."""

    items: list[CleanupItem] = []
    seen: set[Path] = set()

    for target_dir in repo_root.glob("**/target"):
        if any(part in {".git", "node_modules"} for part in target_dir.parts):
            continue

        # Verify it's a Cargo target by checking for CACHEDIR.TAG or debug/release subdirs
        if (
            not (target_dir / "CACHEDIR.TAG").exists()
            and not (target_dir / "debug").exists()
            and not (target_dir / "release").exists()
        ):
            continue

        try:
            resolved = target_dir.resolve()
        except (FileNotFoundError, PermissionError, RuntimeError):
            continue
        if resolved in seen or not target_dir.is_dir():
            continue
        size, _ = _get_dir_size(target_dir)
        if size <= 0:
            continue
        seen.add(resolved)
        items.append(CleanupItem(target_dir, size, is_dir=True))

    return items


def _find_cargo_workspaces(repo_root: Path) -> list[Path]:
    """Find all Cargo workspace roots in the repository.

    Returns directories containing Cargo.toml files that are workspace roots
    or standalone packages.
    """

    workspaces: list[Path] = []
    seen: set[Path] = set()

    for cargo_toml in repo_root.glob("**/Cargo.toml"):
        workspace_dir = cargo_toml.parent

        # Skip if in .git, node_modules, or .flox (dependencies)
        if any(part in {".git", "node_modules", ".flox"} for part in workspace_dir.parts):
            continue

        try:
            resolved = workspace_dir.resolve()
        except (FileNotFoundError, PermissionError, RuntimeError):
            continue

        if resolved in seen:
            continue

        # Check if this is a workspace root or standalone package
        # We look for workspace roots (rust/, cli/, funnel-udf/) and skip members
        try:
            cargo_content = cargo_toml.read_text()
        except (FileNotFoundError, PermissionError, OSError):
            continue

        # If it has [workspace], it's a workspace root
        # If it has package but no workspace.package reference in parent, it's standalone
        is_workspace_root = "[workspace]" in cargo_content

        # For simplicity, we'll run cargo clean on directories that either:
        # 1. Have [workspace] section (workspace roots)
        # 2. Have a target directory (standalone or workspace members with built artifacts)
        if is_workspace_root or (workspace_dir / "target").exists():
            seen.add(resolved)
            workspaces.append(workspace_dir)

    return workspaces


def _describe_items(items: Sequence[CleanupItem], repo_root: Path, heading: str) -> list[str]:
    """Return formatted lines describing a subset of cleanup items."""

    if not items:
        return []

    lines = [heading]
    for item in sorted(items, key=lambda entry: entry.path)[:MAX_SAMPLE_PATHS]:
        try:
            relative = item.path.relative_to(repo_root)
        except ValueError:
            relative = item.path
        lines.append(f"     - {relative} ({_format_size(item.size)})")

    if len(items) > MAX_SAMPLE_PATHS:
        lines.append(f"     … {len(items) - MAX_SAMPLE_PATHS} more")

    return lines


def _delete_items(items: Iterable[CleanupItem]) -> float:
    """Remove files and directories, returning the total freed bytes."""

    freed = 0.0
    for item in items:
        try:
            if item.is_dir:
                shutil.rmtree(item.path)
            else:
                item.path.unlink()
            freed += item.size
        except (FileNotFoundError, PermissionError, OSError):
            continue
    return freed


def _get_dir_size(path: Path, cap: float = float("inf")) -> tuple[float, bool]:
    """Compute directory size, stopping early once *cap* bytes is exceeded.

    Returns ``(accumulated_size, exceeded)``.
    """

    if not path.exists():
        return 0.0, False

    total = 0.0
    stack = [path]

    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                            if total > cap:
                                return total, True
                    except (FileNotFoundError, PermissionError, OSError):
                        continue
        except (FileNotFoundError, PermissionError, NotADirectoryError, OSError):
            continue

    return total, False


def _format_size(bytes_size: float) -> str:
    """Format bytes as a human-readable size string."""

    if bytes_size <= 0:
        return "0.0 B"

    for unit in ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} EiB"


# ---------------------------------------------------------------------------
# doctor:zombies — find and kill orphaned PostHog dev processes
# ---------------------------------------------------------------------------

# Executable basenames that should never be reported as PostHog dev processes.
# Matched against the first token's basename only (not the full args string)
# to avoid false positives from directory names like "/Users/x/code/github/...".
_EXCLUDED_EXECUTABLES: frozenset[str] = frozenset(
    {
        "vim",
        "nvim",
        "emacs",
        "code",
        "codium",
        "git",
        "ssh",
        "tmux",
        "screen",
        "mosh",
        "claude",
        "grep",
        "rg",
        "find",
        "ls",
        "cat",
        "head",
        "tail",
        "sed",
        "awk",
        "ps",
        "lsof",
        "flox-activations",
        "watchman",
        "hogli",
        "docker",
        "dockerd",
        "direnv",
    }
)


@dataclass
class DevProcess:
    """A detected PostHog dev process."""

    pid: int
    ppid: int
    name: str
    cmdline: str
    cpu_percent: float
    memory_rss_kb: int
    start_time: str
    is_orphan: bool
    category: str
    manager: str = ""  # e.g. "phrocs (PID 1234)" for managed processes


@click.command(
    name="doctor:zombies",
    help="Find and kill orphaned PostHog dev processes",
)
@click.option("--dry-run", is_flag=True, help="Show what would be killed without killing")
@click.option("--yes", "-y", is_flag=True, help="Auto-confirm kill of all orphaned processes")
@click.option("--all", "include_all", is_flag=True, help="Include processes under an active phrocs, not just orphans")
def doctor_zombies(dry_run: bool, yes: bool, include_all: bool) -> None:
    """Find and kill orphaned PostHog dev processes left behind after an unclean shutdown."""

    def _record() -> None:
        if not dry_run:
            hints.record_check_run("doctor:zombies")

    click.echo("Scanning for orphaned PostHog dev processes...\n")

    processes = _scan_posthog_processes(REPO_ROOT)

    if not processes:
        click.echo("No PostHog dev processes found. Nothing to clean up.")
        _record()
        return

    orphans = [p for p in processes if p.is_orphan]
    managed = [p for p in processes if not p.is_orphan]
    targets = processes if include_all else orphans

    if not targets:
        click.echo(f"No orphaned processes found ({len(managed)} process(es) under an active process manager).")
        click.echo("Use --all to include managed processes.")
        _record()
        return

    if include_all:
        # Show orphans and managed groups separately
        if orphans:
            _display_process_table(orphans, "Orphaned processes", REPO_ROOT, number_offset=0)
        if managed:
            # Group managed processes by their manager
            managers: dict[str, list[DevProcess]] = {}
            for p in managed:
                managers.setdefault(p.manager, []).append(p)
            offset = len(orphans)
            for mgr, procs in managers.items():
                _display_process_table(procs, f"Managed by {mgr}", REPO_ROOT, number_offset=offset)
                offset += len(procs)
    else:
        _display_process_table(orphans, "Orphaned processes", REPO_ROOT)

    if managed and not include_all:
        # Summarize managed groups
        managed_groups: dict[str, list[DevProcess]] = {}
        for p in managed:
            managed_groups.setdefault(p.manager, []).append(p)
        parts = [f"{len(procs)} under {mgr}" for mgr, procs in managed_groups.items()]
        click.echo(f"   ({', '.join(parts)} — use --all to include)\n")

    total_rss = sum(p.memory_rss_kb for p in targets)
    click.echo(f"   Total: {len(targets)} process(es) using ~{_format_rss(total_rss)}\n")

    if dry_run:
        click.echo("[DRY-RUN] No processes were killed.")
        return

    if yes:
        selected = targets
    else:
        selected = _prompt_process_selection(targets)

    if not selected:
        click.echo("No processes selected. Nothing to do.")
        return

    killed_pids, failed = _kill_processes(selected)
    freed_rss = sum(p.memory_rss_kb for p in selected if p.pid in killed_pids)

    click.echo(f"\nSummary: killed {len(killed_pids)} process(es)")
    if freed_rss > 0:
        click.echo(f"   Freed ~{_format_rss(freed_rss)} RSS")
    if failed > 0:
        click.echo(f"   {failed} process(es) could not be killed")

    _record()


def _scan_posthog_processes(repo_root: Path) -> list[DevProcess]:
    """Find all processes related to the PostHog repo."""

    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pcpu=,rss=,lstart=,args="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        click.echo("Failed to run ps command.")
        return []

    parsed = [p for line in result.stdout.strip().splitlines() if (p := _parse_ps_line(line)) is not None]

    # Build a full PID→(PPID, args) map for ancestor lookups
    all_procs: dict[int, tuple[int, str]] = {pid: (ppid, args) for pid, ppid, _, _, _, args in parsed}

    own_tree = _get_own_process_tree()
    repo_str = str(repo_root)
    repo_prefix = repo_str + "/"

    # Cheap first pass: keep processes that either name the repo path directly, or
    # are a known dev executable whose cwd still needs checking. Defer the cwd
    # lookups so they resolve in a single batched lsof call below instead of
    # spawning lsof once per process — the dominant cost on a busy machine.
    candidates: list[tuple[_PsLine, bool]] = []
    cwd_pids: list[int] = []
    for entry in parsed:
        pid, _, _, _, _, args = entry
        if pid in own_tree or _is_excluded(args):
            continue
        if _matches_repo_path(args, repo_str, repo_prefix):
            candidates.append((entry, True))
        elif _has_known_executable(args):
            candidates.append((entry, False))
            cwd_pids.append(pid)

    cwd_by_pid = _get_process_cwds(cwd_pids)

    processes: list[DevProcess] = []
    for entry, repo_match in candidates:
        pid, ppid, cpu, rss, start_time, args = entry

        if not repo_match:
            cwd = cwd_by_pid.get(pid)
            if cwd is None or not (cwd == repo_str or cwd.startswith(repo_prefix)):
                continue

        name = _extract_process_name(args)
        category = _categorize_process(args)
        is_orphan, manager = _resolve_orphan_status(pid, all_procs)

        processes.append(
            DevProcess(
                pid=pid,
                ppid=ppid,
                name=name,
                cmdline=args,
                cpu_percent=cpu,
                memory_rss_kb=rss,
                start_time=start_time,
                is_orphan=is_orphan,
                category=category,
                manager=manager,
            )
        )

    return processes


def _resolve_orphan_status(pid: int, all_procs: dict[int, tuple[int, str]]) -> tuple[bool, str]:
    """Walk the ancestor chain to determine if a process is orphaned or managed.

    Returns (is_orphan, manager_description).
    A process is orphaned if any ancestor has PPID=1 (reparented to launchd).
    Otherwise, identifies the nearest recognizable manager.
    """

    visited: set[int] = {pid}
    current = pid

    while current in all_procs:
        ppid, args = all_procs[current]

        if ppid <= 1:
            # Reached launchd — this process (or ancestor) is orphaned
            return True, ""

        # Check if the parent is a known process manager
        manager_name = _identify_manager(args)
        if manager_name:
            return False, f"{manager_name} (PID {current})"

        if ppid in visited:
            break
        visited.add(ppid)
        current = ppid

    # Could not determine — treat as managed by unknown parent
    ppid_of_pid = all_procs[pid][0] if pid in all_procs else 0
    return False, f"PID {ppid_of_pid}"


_KNOWN_MANAGERS = (
    ("phrocs", "phrocs"),
    ("mprocs", "mprocs"),
    ("overmind", "overmind"),
    ("foreman", "foreman"),
    ("honcho", "honcho"),
    ("supervisord", "supervisord"),
    ("zellij", "zellij"),
    ("tmux", "tmux"),
    ("screen", "screen"),
    ("kitty", "kitty"),
    ("alacritty", "alacritty"),
    ("wezterm", "wezterm"),
    ("Terminal", "Terminal.app"),
    ("iTerm", "iTerm2"),
)


def _identify_manager(args: str) -> str | None:
    """Check if a command line belongs to a known process manager or terminal."""

    for keyword, display_name in _KNOWN_MANAGERS:
        if keyword in args:
            return display_name
    return None


_PsLine = tuple[int, int, float, int, str, str]


def _parse_ps_line(line: str) -> _PsLine | None:
    """Parse a single ps output line into (pid, ppid, cpu%, rss_kb, start_time, args)."""

    parts = line.split()
    # Need at least: pid ppid cpu rss + 5 date tokens + 1 args token = 10
    if len(parts) < 10:
        return None

    try:
        pid = int(parts[0])
        ppid = int(parts[1])
        cpu = float(parts[2])
        rss = int(parts[3])
    except (ValueError, IndexError):
        return None

    # lstart is always 5 tokens: Day Mon DD HH:MM:SS YYYY
    start_time = " ".join(parts[4:9])
    args = " ".join(parts[9:])

    return pid, ppid, cpu, rss, start_time, args


def _get_own_process_tree() -> set[int]:
    """Return PIDs of the current process and all its ancestors up to PID 1."""

    pids: set[int] = set()
    pid = os.getpid()

    # Walk up the PPID chain
    while pid > 1:
        pids.add(pid)
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            break
        try:
            pid = int(result.stdout.strip())
        except ValueError:
            break

    return pids


def _matches_repo_path(args: str, repo_str: str, repo_prefix: str) -> bool:
    """Check if the command line references the exact repo path (not a prefix like posthog.com)."""

    idx = 0
    while True:
        idx = args.find(repo_str, idx)
        if idx == -1:
            return False
        end = idx + len(repo_str)
        # The character after repo_str (if any) must be / or whitespace, not e.g. ".com"
        if end >= len(args) or args[end] in ("/", " ", "\t"):
            return True
        idx = end


def _is_excluded(args: str) -> bool:
    """Check if the executable basename is in the exclusion set."""
    if not args or not args.strip():
        return False
    basename = args.split()[0].rsplit("/", 1)[-1]
    return basename in _EXCLUDED_EXECUTABLES


def _has_known_executable(args: str) -> bool:
    """Check if the command starts with a known PostHog dev executable."""

    known = ("python", "node", "celery", "granian", "uvicorn", "dagster", "cargo", "air", "tsx", "esbuild", "pnpm")
    first_word = args.split()[0].rsplit("/", 1)[-1] if args else ""
    return first_word in known


def _get_process_cwds(pids: Sequence[int]) -> dict[int, str]:
    """Map each pid to its working directory via a single lsof call.

    ``-a`` ANDs the ``-p`` (pid set) and ``-d cwd`` (fd) selectors; without it
    lsof ORs them and reports *every* process's cwd — slow (a full-system scan
    per pid) and wrong (attributing the first process's cwd to the queried pid).
    ``-Fpn`` emits pid/name fields so each cwd attributes back to its pid; with
    ``-d cwd`` each process yields exactly one name line.
    """
    if not pids:
        return {}

    try:
        result = subprocess.run(
            ["lsof", "-a", "-p", ",".join(str(pid) for pid in pids), "-d", "cwd", "-Fpn"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return {}

    # lsof exits non-zero when any queried pid has vanished, but still emits valid
    # records for the survivors — parse whatever stdout we got.
    cwds: dict[int, str] = {}
    current: int | None = None
    for line in result.stdout.splitlines():
        tag, value = line[:1], line[1:]
        if tag == "p":
            current = int(value) if value.isdigit() else None
        elif tag == "n" and current is not None:
            cwds[current] = value
    return cwds


def _extract_process_name(args: str) -> str:
    """Extract a short display name from a full command line."""

    first = args.split()[0] if args else ""
    return first.rsplit("/", 1)[-1]


def _categorize_process(args: str) -> str:
    """Return a category string based on the command line."""

    lower = args.lower()
    if any(kw in lower for kw in ("python", "celery", "granian", "uvicorn", "dagster", "gunicorn")):
        return "python"
    if any(kw in lower for kw in ("node", "tsx", "esbuild", "pnpm", "vite")):
        return "node"
    if any(
        kw in lower
        for kw in (
            "cargo",
            "capture",
            "feature-flags",
            "property-defs-rs",
            "cymbal",
            "cyclotron",
            "personhog",
            "batch-import",
        )
    ):
        return "rust"
    if any(kw in lower for kw in ("air", "livestream")):
        return "go"
    if "/bin/bash" in lower or "/bin/sh" in lower or "/bin/zsh" in lower:
        return "shell"
    return "other"


def _display_process_table(processes: list[DevProcess], heading: str, repo_root: Path, number_offset: int = 0) -> None:
    """Display a numbered table of processes."""

    click.echo(f"   {heading}:\n")
    click.echo(f"   {'#':>3}  {'PID':>7}  {'CPU%':>5}  {'MEM':>9}  COMMAND")

    repo_str = str(repo_root)
    max_cmd_width = 90
    for i, proc in enumerate(processes, number_offset + 1):
        summary = _summarize_cmdline(proc.cmdline, repo_str)
        if len(summary) > max_cmd_width:
            summary = summary[:max_cmd_width] + "..."
        click.echo(
            f"   {i:>3}  {proc.pid:>7}  {proc.cpu_percent:>4.1f}%  {_format_rss(proc.memory_rss_kb):>9}  {summary}"
        )

    click.echo()


# Patterns for cleaning up command lines for display
_NIX_STORE_BIN_RE = re.compile(r"/nix/store/[^/]+/bin/([^\s]+)")
_FLOX_BIN_RE = re.compile(r"\S*\.flox/(?:cache/venv|run/[^/]+\.[^/]+)/bin/([^\s]+)")
_NODE_MODULES_BIN_RE = re.compile(r"\S*node_modules/\.bin/(?:\.\./)?([^/]+)/dist/cli\.mjs")
_NODE_MODULES_PKG_RE = re.compile(r"\S*node_modules/\.pnpm/[^/]+/node_modules/([^/]+)/dist/\S+")
_TSX_LOADER_RE = re.compile(r"\s*--(?:require|import)\s+(?:file://)?\S*tsx/dist/\S+")
_FILE_URL_RE = re.compile(r"file:///")


def _summarize_cmdline(cmdline: str, repo_str: str) -> str:
    """Produce a short, human-readable version of a process command line."""

    s = cmdline

    # Replace nix store binary paths with just the binary name
    s = _NIX_STORE_BIN_RE.sub(r"\1", s)

    # Replace .flox/cache/venv/bin/X and .flox/run/.../bin/X with just X
    s = _FLOX_BIN_RE.sub(r"\1", s)

    # Strip tsx --require/--import loader boilerplate
    s = _TSX_LOADER_RE.sub("", s)

    # Replace node_modules/.bin/../pkg/dist/cli.mjs with just pkg
    s = _NODE_MODULES_BIN_RE.sub(r"\1", s)

    # Replace deep node_modules/.pnpm paths with just the package name
    s = _NODE_MODULES_PKG_RE.sub(r"\1", s)

    # Strip file:// prefixes
    s = _FILE_URL_RE.sub("", s)

    # Strip the repo root prefix from remaining paths
    s = s.replace(repo_str + "/", "")

    # Use python3 → python for consistency
    if s.startswith("python3 "):
        s = "python " + s[8:]

    # Collapse multiple spaces
    s = re.sub(r"  +", " ", s).strip()

    return s


def _prompt_process_selection(processes: list[DevProcess]) -> list[DevProcess]:
    """Prompt the user to select which processes to kill."""

    response = click.prompt(
        f"   Kill all {len(processes)} process(es)? [y/N]\n   Or enter specific numbers (e.g. 1,3,5)",
        default="n",
        show_default=False,
    )

    if response.lower() in ("y", "yes"):
        return processes

    if response.lower() in ("n", "no", "q", "quit"):
        return []

    # Parse comma-separated numbers, deduplicating
    selected: list[DevProcess] = []
    seen: set[int] = set()
    for part in response.split(","):
        part = part.strip()
        try:
            idx = int(part)
            if 1 <= idx <= len(processes):
                proc = processes[idx - 1]
                if proc.pid not in seen:
                    seen.add(proc.pid)
                    selected.append(proc)
            else:
                click.echo(f"   Ignoring out-of-range number: {idx}")
        except ValueError:
            click.echo(f"   Ignoring invalid input: {part}")

    return selected


def _kill_processes(processes: list[DevProcess]) -> tuple[set[int], int]:
    """Kill processes with SIGTERM, then SIGKILL for survivors. Returns (killed_pids, failed_count)."""

    # Build kill order: leaf processes first (those with no children in our list)
    parents = [p for p in processes if any(c.ppid == p.pid for c in processes)]
    leaves = [p for p in processes if p not in parents]
    ordered = leaves + parents

    click.echo(f"Sending SIGTERM to {len(ordered)} process(es)...")

    killed_pids: set[int] = set()
    failed = 0
    still_alive: list[DevProcess] = []

    for proc in ordered:
        try:
            os.kill(proc.pid, signal.SIGTERM)
            still_alive.append(proc)
        except ProcessLookupError:
            click.echo(f"   PID {proc.pid} ({proc.name}) already exited")
            killed_pids.add(proc.pid)
        except PermissionError:
            click.echo(f"   PID {proc.pid} ({proc.name}) permission denied")
            failed += 1

    # Poll for up to 5 seconds
    for _ in range(10):
        if not still_alive:
            break
        time.sleep(0.5)
        remaining: list[DevProcess] = []
        for proc in still_alive:
            try:
                os.kill(proc.pid, 0)
                remaining.append(proc)
            except ProcessLookupError:
                click.echo(f"   PID {proc.pid} ({proc.name}) terminated")
                killed_pids.add(proc.pid)
            except PermissionError:
                # Still alive but we lost permission somehow
                remaining.append(proc)
        still_alive = remaining

    # SIGKILL survivors
    for proc in still_alive:
        try:
            click.echo(f"   PID {proc.pid} ({proc.name}) did not exit after 5s, sending SIGKILL...")
            os.kill(proc.pid, signal.SIGKILL)
            killed_pids.add(proc.pid)
            click.echo(f"   PID {proc.pid} ({proc.name}) force-killed")
        except ProcessLookupError:
            click.echo(f"   PID {proc.pid} ({proc.name}) exited during escalation")
            killed_pids.add(proc.pid)
        except PermissionError:
            click.echo(f"   PID {proc.pid} ({proc.name}) permission denied for SIGKILL")
            failed += 1

    return killed_pids, failed


def _format_rss(rss_kb: int) -> str:
    """Format RSS in KB as a human-readable size string."""

    if rss_kb < 1024:
        return f"{rss_kb} KB"
    mb = rss_kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.1f} GB"


# ---------------------------------------------------------------------------
# doctor — unified health check
# ---------------------------------------------------------------------------


class CheckStatus(enum.Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    summary: str
    remediation: str | None = None


_DISK_WARNING_THRESHOLD = 1024 * 1024 * 1024  # 1 GB


def _check_disk(repo_root: Path) -> CheckResult:
    """Fast disk usage probe for the doctor summary.

    Uses depth-limited globs (no ``**``) and early-exit size counting so the
    check completes in hundreds of milliseconds instead of seconds.  The
    detailed ``doctor:disk`` command still uses the full estimators.
    """
    budget = float(_DISK_WARNING_THRESHOLD)
    total = 0.0

    # Flox logs — already cheap (single-directory glob)
    flox_est = _estimate_flox_logs(repo_root)
    total += flox_est.total_size

    # Python caches — depth-limited instead of repo_root.glob("**/{pattern}")
    _SKIP_PARTS = {".git", "node_modules", ".venv", "venv"}
    seen: set[Path] = set()
    for pattern in PYTHON_CACHE_PATTERNS:
        for depth in ("*", "*/*", "*/*/*"):
            for cache_dir in repo_root.glob(f"{depth}/{pattern}"):
                if _SKIP_PARTS & set(cache_dir.parts):
                    continue
                try:
                    resolved = cache_dir.resolve()
                except (FileNotFoundError, PermissionError, RuntimeError):
                    continue
                if resolved in seen or not cache_dir.is_dir():
                    continue
                seen.add(resolved)
                size, exceeded = _get_dir_size(cache_dir, cap=budget - total)
                total += size
                if exceeded:
                    return CheckResult(
                        name="Disk usage",
                        status=CheckStatus.WARNING,
                        summary=f">{_format_size(budget)} reclaimable",
                        remediation="run `hogli doctor:disk`",
                    )

    # Node artifacts — patterns are mostly concrete paths; use capped sizing
    node_seen: set[Path] = set()
    for pattern in NODE_ARTIFACT_PATTERNS:
        for path in repo_root.glob(pattern):
            try:
                resolved = path.resolve()
            except (FileNotFoundError, PermissionError, RuntimeError):
                continue
            if resolved in node_seen:
                continue
            node_seen.add(resolved)
            if path.is_dir():
                size, exceeded = _get_dir_size(path, cap=budget - total)
                total += size
            else:
                try:
                    total += path.stat().st_size
                except (FileNotFoundError, PermissionError, OSError):
                    continue
            if total > budget:
                return CheckResult(
                    name="Disk usage",
                    status=CheckStatus.WARNING,
                    summary=f">{_format_size(budget)} reclaimable",
                    remediation="run `hogli doctor:disk`",
                )

    if total > 0:
        return CheckResult(
            name="Disk usage",
            status=CheckStatus.OK,
            summary=f"{_format_size(total)} reclaimable",
        )
    return CheckResult(name="Disk usage", status=CheckStatus.OK, summary="clean")


def _check_zombies(repo_root: Path) -> CheckResult:
    """Quick orphan process scan."""
    processes = _scan_posthog_processes(repo_root)
    orphans = [p for p in processes if p.is_orphan]
    if orphans:
        return CheckResult(
            name="Zombie processes",
            status=CheckStatus.WARNING,
            summary=f"{len(orphans)} orphaned",
            remediation="run `hogli doctor:zombies`",
        )
    return CheckResult(
        name="Zombie processes",
        status=CheckStatus.OK,
        summary="0 orphaned",
    )


def _check_docker() -> CheckResult:
    """Check whether the Docker daemon is reachable.

    Uses ``docker version`` instead of ``docker info`` — it only pings the
    daemon for its version string rather than fetching full system metadata,
    which is significantly faster (~200 ms vs ~1-3 s).
    """
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            return CheckResult(name="Docker", status=CheckStatus.OK, summary="daemon running")
        return CheckResult(
            name="Docker",
            status=CheckStatus.ERROR,
            summary="daemon not responding",
            remediation="start Docker Desktop or OrbStack",
        )
    except FileNotFoundError:
        return CheckResult(
            name="Docker",
            status=CheckStatus.ERROR,
            summary="not installed",
            remediation="install Docker Desktop or OrbStack",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Docker",
            status=CheckStatus.ERROR,
            summary="timed out",
            remediation="start Docker Desktop or OrbStack",
        )


def _check_migrations() -> CheckResult:
    """Check for unapplied Django migrations."""
    try:
        from hogli_commands.migrations import _compute_migration_diff

        diff = _compute_migration_diff()
        pending = len(diff.pending)
        orphaned = len(diff.orphaned)
        parts: list[str] = []
        if pending:
            parts.append(f"{pending} unapplied")
        if orphaned:
            parts.append(f"{orphaned} orphaned")
        if parts:
            return CheckResult(
                name="Migrations",
                status=CheckStatus.WARNING,
                summary=", ".join(parts),
                remediation="run `hogli migrations:sync`",
            )
        return CheckResult(name="Migrations", status=CheckStatus.OK, summary="in sync")
    except SystemExit:
        return CheckResult(
            name="Migrations",
            status=CheckStatus.ERROR,
            summary="could not connect to database",
            remediation="start the dev environment with `hogli start`",
        )
    except Exception as e:
        return CheckResult(
            name="Migrations",
            status=CheckStatus.ERROR,
            summary=str(e)[:60],
        )


_STATUS_COLORS = {
    CheckStatus.OK: "green",
    CheckStatus.WARNING: "yellow",
    CheckStatus.ERROR: "red",
}

_STATUS_LABELS = {
    CheckStatus.OK: "OK",
    CheckStatus.WARNING: "WARNING",
    CheckStatus.ERROR: "ERROR",
}


def _print_check_result(result: CheckResult) -> None:
    """Print a single check result as a dotted status line."""
    label = _STATUS_LABELS[result.status]
    color = _STATUS_COLORS[result.status]
    name_padded = f"  {result.name} ".ljust(28, ".")
    status_text = click.style(f" {label}", fg=color, bold=True)
    click.echo(f"{name_padded}{status_text} ({result.summary})")
    if result.remediation:
        click.echo(f"{'':>30}{result.remediation}")


def _run_checks(repo_root: Path) -> list[CheckResult]:
    """Run all health checks concurrently and return results in declared order."""
    checks: list[Callable[[], CheckResult]] = [
        lambda: _check_disk(repo_root),
        lambda: _check_zombies(repo_root),
        _check_docker,
        _check_migrations,
    ]

    # Each check is I/O-bound and independent, so fan them out across threads.
    results: list[CheckResult | None] = [None] * len(checks)
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        future_to_idx = {pool.submit(fn): i for i, fn in enumerate(checks)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = CheckResult(
                    name=f"Check {idx + 1}",
                    status=CheckStatus.ERROR,
                    summary=f"Check failed with error: {str(e)}",
                )

    return [r for r in results if r is not None]


@click.command(name="doctor", help="Quick health check for your dev environment")
def doctor() -> None:
    """Run non-destructive checks and print a status summary."""
    click.echo("\nhogli doctor\n")

    results = _run_checks(REPO_ROOT)

    for result in results:
        _print_check_result(result)

    click.echo()

    warnings = sum(1 for r in results if r.status == CheckStatus.WARNING)
    errors = sum(1 for r in results if r.status == CheckStatus.ERROR)
    if warnings == 0 and errors == 0:
        click.secho("  All checks passed.", fg="green")
    else:
        parts: list[str] = []
        if errors:
            parts.append(f"{errors} error(s)")
        if warnings:
            parts.append(f"{warnings} warning(s)")
        click.secho(f"  {', '.join(parts)} found.", fg="yellow")

    click.echo()

    hints.record_check_run("doctor")


# ---------------------------------------------------------------------------
# doctor:report — paste-ready diagnostics dump for devex triage
# ---------------------------------------------------------------------------


def _run_output(cmd: Sequence[str], timeout: float = 5.0) -> str | None:
    """Run a command and return its trimmed stdout, or None on any failure."""
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _format_kv_block(pairs: Sequence[tuple[str, str]]) -> list[str]:
    """Render label/value pairs as left-aligned ``label  value`` lines."""
    width = max((len(label) for label, _ in pairs), default=0)
    return [f"{label.ljust(width)}  {value}" for label, value in pairs]


def _system_info() -> list[tuple[str, str]]:
    """Collect OS, shell, and terminal context (terminal matters for TUI bugs)."""
    if platform.system() == "Darwin":
        mac_ver = platform.mac_ver()[0]
        os_desc = f"macOS {mac_ver} (Darwin {platform.release()})" if mac_ver else f"Darwin {platform.release()}"
    else:
        os_desc = platform.platform()
    return [
        ("os", os_desc),
        ("arch", platform.machine()),
        ("shell", os.environ.get("SHELL", "unknown")),
        ("term", os.environ.get("TERM", "unset")),
        ("term_program", os.environ.get("TERM_PROGRAM", "unset")),
        ("locale", os.environ.get("LANG", "unset")),
    ]


def _repo_info(repo_root: Path) -> list[tuple[str, str]]:
    """Collect git branch, HEAD, and working-tree dirtiness."""
    repo_str = str(repo_root)
    git = ["git", "-C", repo_str]
    branch = _run_output([*git, "rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    commit = _run_output([*git, "log", "-1", "--format=%h %s"]) or "unknown"
    status = _run_output([*git, "status", "--porcelain"])
    dirty_count = len(status.splitlines()) if status else 0

    pairs = [
        ("path", repo_str),
        ("branch", branch),
        ("commit", commit),
        ("dirty", "clean" if dirty_count == 0 else f"{dirty_count} uncommitted file(s)"),
    ]
    if ".claude/worktrees/" in repo_str:
        pairs.append(("worktree", "yes"))
    return pairs


def _normalize_arch(value: str) -> str:
    """Map the many spellings of an architecture to a canonical token."""
    v = value.lower()
    if v in {"arm64", "aarch64"}:
        return "arm64"
    if v in {"x86_64", "x86-64", "amd64"}:
        return "x86_64"
    return v


def _binary_arches(path: str) -> set[str]:
    """Best-effort set of architectures a binary contains, via ``file``.

    Empty when ``file`` is unavailable or the arch is indeterminate — callers
    must treat empty as "unknown", not "mismatch", to avoid false alarms.
    """
    out = _run_output(["file", "-b", path])
    if not out:
        return set()
    lowered = out.lower()
    return {_normalize_arch(token) for token in ("arm64", "aarch64", "x86_64", "x86-64", "amd64") if token in lowered}


def _phrocs_info() -> tuple[str, str]:
    """Diagnose phrocs, which powers the ``hogli start`` TUI.

    A blank ``hogli start`` screen most often traces back to phrocs being
    missing, present-but-unrunnable, or built for the wrong architecture
    (e.g. an x86_64 binary under Rosetta on Apple Silicon), so surface all
    three explicitly rather than just the version.
    """
    path = shutil.which("phrocs")
    if not path:
        return ("phrocs", "MISSING — `hogli start` TUI needs it (see tools/phrocs/install.sh)")

    version = _run_output([path, "--version"]) or "installed (--version failed — binary may be broken)"

    arches = _binary_arches(path)
    host = _normalize_arch(platform.machine())
    arch_label = f" [{'/'.join(sorted(arches))}]" if arches else ""
    mismatch = f" — ARCH MISMATCH vs host {host}; likely blank-TUI cause" if arches and host not in arches else ""

    return ("phrocs", f"{version}{arch_label} ({path}){mismatch}")


def _toolchain_info(repo_root: Path) -> list[tuple[str, str]]:
    """Collect runtime/toolchain versions relevant to running the dev stack."""
    pairs: list[tuple[str, str]] = [("python", f"{platform.python_version()} ({sys.executable})")]

    node = _run_output(["node", "--version"])
    if node:
        nvmrc = repo_root / ".nvmrc"
        expected = nvmrc.read_text().strip() if nvmrc.exists() else ""
        suffix = ""
        if expected:
            actual_major = node.lstrip("v").split(".")[0]
            expected_major = expected.lstrip("v").split(".")[0]
            suffix = " (.nvmrc ok)" if actual_major == expected_major else f" (.nvmrc wants {expected})"
        pairs.append(("node", f"{node}{suffix}"))
    else:
        pairs.append(("node", "not found"))

    pairs.append(("pnpm", _run_output(["pnpm", "--version"]) or "not found"))

    flox_ver = _run_output(["flox", "--version"])
    if os.environ.get("FLOX_ENV_DESCRIPTION") or os.environ.get("FLOX_ENV"):
        pairs.append(("flox", f"active — {flox_ver}" if flox_ver else "active"))
    elif flox_ver:
        pairs.append(("flox", f"not active ({flox_ver} on PATH)"))
    else:
        pairs.append(("flox", "not on PATH"))

    docker_ver = _run_output(["docker", "version", "--format", "{{.Server.Version}}"], timeout=3.0)
    pairs.append(("docker", f"{docker_ver} (daemon running)" if docker_ver else "daemon not responding"))

    pairs.append(_phrocs_info())

    return pairs


def _checks_info(repo_root: Path) -> list[tuple[str, str]]:
    """Run the doctor health checks and flatten them into label/value pairs."""
    pairs: list[tuple[str, str]] = []
    for result in _run_checks(repo_root):
        value = f"{_STATUS_LABELS[result.status]} ({result.summary})"
        if result.remediation:
            value += f" → {result.remediation}"
        pairs.append((result.name.lower().replace(" ", "_"), value))
    return pairs


def _generated_config_path(repo_root: Path) -> Path:
    """Resolve the generated mprocs config phrocs renders, read-only.

    Mirrors ``hogli``'s lookup (the ``HOGLI_MPROCS_PATH`` override, else
    ``.posthog/.generated/mprocs.yaml`` at the repo root) without the worktree
    symlink-creating fallback — a diagnostic must not mutate the workspace.
    """
    override = os.environ.get("HOGLI_MPROCS_PATH")
    if override:
        return Path(override)
    return repo_root / ".posthog" / ".generated" / "mprocs.yaml"


def _phrocs_socket_path(repo_root: Path) -> Path:
    """Replicate phrocs' per-workspace IPC socket path (ipc.SocketPathFor):
    ``/tmp/phrocs-<first 4 bytes of sha256(real absolute cwd)>.sock``.
    """
    real = os.path.realpath(repo_root)
    digest = hashlib.sha256(real.encode()).digest()[:4].hex()
    return Path(f"/tmp/phrocs-{digest}.sock")


def _config_procs(config: Path) -> str:
    """Summarize a generated mprocs config's proc set; a parse failure is itself
    the diagnosis, since phrocs can't render an unparseable config."""
    try:
        data = yaml.safe_load(config.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return f"unparseable: {str(exc)[:60]}"
    procs = data.get("procs") if isinstance(data, dict) else None
    if not isinstance(procs, dict):
        return "no procs"
    return f"{len(procs)} procs"


def _tail(path: Path, lines: int) -> list[str]:
    """Last ``lines`` lines of a text file, or [] if it can't be read."""
    try:
        content = path.read_text(errors="replace")
    except OSError:
        return []
    return content.splitlines()[-lines:]


def _iso_mtime(path: Path) -> str:
    # Diagnostics run when the env misbehaves, so the file can vanish between an
    # exists() check and this stat() — degrade instead of sinking the report.
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return "unavailable"


def _phrocs_runtime_pairs(repo_root: Path) -> list[tuple[str, str]]:
    """phrocs/start runtime state — the layer past the binary that explains a
    blank or broken ``hogli start`` TUI: the generated config phrocs renders,
    its IPC socket, and the terminal it draws into.
    """
    config = _generated_config_path(repo_root)
    pairs: list[tuple[str, str]] = []

    if config.exists():
        pairs.append(("generated_config", f"{config} ({_config_procs(config)}, {_iso_mtime(config)})"))
    else:
        pairs.append(("generated_config", f"MISSING ({config}) — run `hogli dev:generate`"))

    log = config.parent / "logs" / "phrocs.log"
    pairs.append(("phrocs_log", f"{log} ({_iso_mtime(log)})" if log.exists() else f"absent ({log})"))

    socket = _phrocs_socket_path(repo_root)
    pairs.append(
        ("ipc_socket", f"present ({socket}) — stale if no phrocs running" if socket.exists() else f"none ({socket})")
    )

    pairs.append(("stdout_tty", "yes" if sys.stdout.isatty() else "no — phrocs opens /dev/tty as a fallback"))
    try:
        size = os.get_terminal_size()
        pairs.append(("terminal_size", f"{size.columns}x{size.lines}"))
    except OSError:
        pairs.append(("terminal_size", "unavailable (no controlling terminal)"))

    return pairs


def _phrocs_runtime_block(repo_root: Path) -> list[str]:
    """The full verbose ``phrocs runtime`` section body: state pairs plus a tail
    of phrocs' own log (the highest-signal evidence when it started then died)."""
    block = _format_kv_block(_phrocs_runtime_pairs(repo_root))
    tail = _tail(_generated_config_path(repo_root).parent / "logs" / "phrocs.log", 15)
    if tail:
        block.append("")
        block.append("phrocs.log (last 15 lines):")
        block.extend(f"  {line}" for line in tail)
    return block


class _ManifestLike(Protocol):
    """The slice of ``hogli.manifest.Manifest`` the import probe relies on."""

    config: dict

    def get_all_commands(self) -> list[str]: ...

    def get_command_config(self, command_name: str) -> dict | None: ...


def _collect_import_targets(manifest: _ManifestLike) -> list[tuple[str, str, str | None]]:
    """Enumerate ``(label, module_path, attr)`` for every importable command + boot module.

    ``attr`` is the click command symbol for ``click:`` entries, or ``None`` for
    boot modules (which we only need to import, not resolve an attribute on).
    Command discovery and the metadata/config skip rules are delegated to the
    manifest API so this stays in lockstep with the framework's schema.
    """
    targets: list[tuple[str, str, str | None]] = []

    for cmd_name in manifest.get_all_commands():
        click_str = (manifest.get_command_config(cmd_name) or {}).get("click")
        if isinstance(click_str, str) and click_str.count(":") == 1:
            module_path, attr = click_str.split(":", 1)
            if module_path and attr:
                targets.append((cmd_name, module_path, attr))

    for module_path in manifest.config.get("boot_modules", []) or []:
        if isinstance(module_path, str) and module_path:
            targets.append((module_path, module_path, None))

    return targets


def _probe_command_imports(manifest: _ManifestLike) -> tuple[int, list[tuple[str, str]]]:
    """Import every command + boot module, returning ``(probed, failures)``.

    Surfaces broken modules that would otherwise fail opaquely at invoke time —
    a common cause of confusing ``hogli`` startup behaviour.
    """
    targets = _collect_import_targets(manifest)
    module_cache: dict[str, object] = {}
    failures: list[tuple[str, str]] = []

    for label, module_path, attr in targets:
        if module_path not in module_cache:
            try:
                module_cache[module_path] = importlib.import_module(module_path)
            except Exception as exc:
                module_cache[module_path] = exc
        module = module_cache[module_path]
        if isinstance(module, Exception):
            failures.append((label, f"{type(module).__name__}: {str(module)[:120]}"))
        elif attr is not None and not hasattr(module, attr):
            failures.append((label, f"missing attribute '{attr}'"))

    return len(targets), failures


def _build_report(repo_root: Path, manifest: _ManifestLike) -> str:
    """Assemble the full diagnostics report body (no surrounding code fence)."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [f"hogli doctor:report — {timestamp}"]

    # Each collector shells out to independent binaries (git, node, docker, …),
    # so gather them concurrently — a single hung tool can't serialize the whole
    # report, which matters since this runs precisely when the env misbehaves.
    sections: list[tuple[str, Callable[[], list[tuple[str, str]]]]] = [
        ("System", _system_info),
        ("Repo", lambda: _repo_info(repo_root)),
        ("Toolchain", lambda: _toolchain_info(repo_root)),
        ("Checks", lambda: _checks_info(repo_root)),
    ]
    collected: list[list[tuple[str, str]]] = [[] for _ in sections]
    with ThreadPoolExecutor(max_workers=len(sections) + 1) as pool:
        # The import probe is independent of the section collectors, so run it in
        # the same batch rather than serially afterwards — it overlaps with the
        # slowest section instead of adding its cost on top.
        probe_future = pool.submit(_probe_command_imports, manifest)
        futures = {pool.submit(collect): i for i, (_, collect) in enumerate(sections)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                collected[idx] = future.result()
            except Exception as exc:
                # A diagnostic is run precisely when the env misbehaves — one
                # collector blowing up must not sink the whole report.
                collected[idx] = [("error", f"{type(exc).__name__}: {str(exc)[:120]}")]
        try:
            probed, failures = probe_future.result()
        except Exception as exc:
            # Same invariant as the section collectors above: the import probe
            # blowing up must not sink the whole report.
            probed, failures = 0, [("import probe", f"{type(exc).__name__}: {str(exc)[:120]}")]

    for (title, _), pairs in zip(sections, collected):
        lines.append("")
        lines.append(f"== {title} ==")
        lines.extend(_format_kv_block(pairs))

    # phrocs is the headline failure mode (blank `hogli start`), so group its
    # runtime state right after the toolchain/health sections.
    lines.append("")
    lines.append("== phrocs runtime ==")
    lines.extend(_phrocs_runtime_block(repo_root))

    lines.append("")
    lines.append("== Command imports ==")
    if not failures:
        lines.append(f"probed {probed} target(s): all import OK")
    else:
        lines.append(f"probed {probed} target(s): {len(failures)} FAILED")
        lines.extend(f"  {label}: {error}" for label, error in failures)

    return "\n".join(lines)


@click.command(
    name="doctor:report",
    help="Dump a paste-ready dev-environment diagnostics report for devex triage",
)
def doctor_report() -> None:
    """Collect environment, toolchain, health-check, command-import, and phrocs
    runtime diagnostics into a single copy-paste block to share with the devex team."""
    click.echo("\nGathering diagnostics…\n")
    report = _build_report(REPO_ROOT, get_manifest())

    click.echo("```text")
    click.echo(report)
    click.echo("```")
    click.echo()

    hints.record_check_run("doctor:report")
