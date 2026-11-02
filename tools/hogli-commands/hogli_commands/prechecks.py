"""Precheck handlers for hogli command lifecycle.

Precheck handlers run before composite commands execute (see ``steps:`` /
``prechecks:`` entries in hogli.yaml). They register against
``hogli.hooks.register_precheck`` at boot, and the heavy work happens lazily
inside the handler — keep this module light to import.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

import click
from hogli.hooks import register_precheck
from hogli.manifest import REPO_ROOT

from hogli_commands.telemetry_props import _detect_environment

_GIB = 1024**3
_DEFAULT_MIN_FREE_GIB = 20.0
_DEFAULT_MAX_WORKTREES = 3
_MIN_FREE_GIB_ENV = "HOGLI_WORKTREE_DISK_MIN_FREE_GIB"
_MAX_WORKTREES_ENV = "HOGLI_WORKTREE_DISK_MAX_WORKTREES"
_CLEAN_PREVIEW_COMMAND = "hogli worktrees:clean --before 7d --mode deps --dry-run"


def _migrations_precheck(check: dict, yes: bool) -> bool | None:
    """Warn (and optionally block) when applied migrations don't exist in code."""
    # Lazy import: pulls the migrations command module only when this precheck
    # actually fires (i.e. when a `prechecks: [{type: migrations}]` step runs),
    # not at boot.
    from hogli_commands.migrations import _compute_migration_diff, _get_cached_migration

    try:
        diff = _compute_migration_diff()

        if diff.orphaned:
            click.echo()
            click.secho("⚠️  Orphaned migrations detected!", fg="yellow", bold=True)
            click.echo("These migrations are applied in the DB but don't exist in code.")
            click.echo("They were likely applied on another branch.\n")

            for m in diff.orphaned:
                cached = "cached" if _get_cached_migration(m.app, m.name) else "not cached"
                click.echo(f"    {m.app}: {m.name} ({cached})")
            click.echo()

            click.echo("Run 'hogli migrations:sync' to roll them back.\n")

            if not yes:
                if not click.confirm("Continue anyway?", default=False):
                    click.echo("Aborted. Run 'hogli migrations:sync' first.")
                    return False

    except Exception as e:
        # Don't block start if migration check fails (e.g., DB not running)
        click.secho(f"⚠️  Could not check migrations: {e}", fg="yellow", err=True)

    return None


def should_warn_about_worktree_disk(
    free_bytes: int, linked_worktrees: int, min_free_gib: float, max_worktrees: int
) -> bool:
    return free_bytes < min_free_gib * _GIB and linked_worktrees > max_worktrees


def _threshold(env_var: str, configured: Any, default: float) -> float:
    for candidate in (os.environ.get(env_var), configured):
        if candidate is None or candidate == "":
            continue
        try:
            return float(candidate)
        except (TypeError, ValueError):
            continue
    return default


def _count_linked_worktrees() -> int | None:
    try:
        porcelain = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    all_worktrees = sum(1 for line in porcelain.splitlines() if line.startswith("worktree "))
    return max(0, all_worktrees - 1)


def _worktree_disk_precheck(check: dict, yes: bool) -> None:
    """Point at `hogli worktrees:clean` when free disk is low and many worktrees exist. Never blocks."""
    try:
        if _detect_environment() == "ci" or os.environ.get("POSTHOG_TASK_RUN_ID"):
            return None
        min_free_gib = _threshold(_MIN_FREE_GIB_ENV, check.get("min_free_gib"), _DEFAULT_MIN_FREE_GIB)
        max_worktrees = int(_threshold(_MAX_WORKTREES_ENV, check.get("max_worktrees"), _DEFAULT_MAX_WORKTREES))
        free_bytes = shutil.disk_usage(REPO_ROOT).free
        if free_bytes >= min_free_gib * _GIB:
            return None
        linked_worktrees = _count_linked_worktrees()
        if linked_worktrees is None:
            return None
        if should_warn_about_worktree_disk(free_bytes, linked_worktrees, min_free_gib, max_worktrees):
            click.secho(
                f"⚠️  {free_bytes / _GIB:.1f} GiB free on this disk and {linked_worktrees} git worktrees exist. "
                f"See what you can reclaim with `{_CLEAN_PREVIEW_COMMAND}`.",
                fg="yellow",
                err=True,
            )
    except Exception:
        pass
    return None


register_precheck("migrations", _migrations_precheck)
register_precheck("worktree_disk", _worktree_disk_precheck)
