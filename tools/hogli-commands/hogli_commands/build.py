"""Unified build command with smart change detection."""

from __future__ import annotations

import fnmatch
import subprocess

import click
from hogli.cli import cli
from hogli.manifest import REPO_ROOT

# command -> file globs that should trigger it
TRIGGERS: dict[str, tuple[str, ...]] = {
    "build:schema": (
        "frontend/src/queries/schema/*",
        "posthog/schema_migrations/*",
    ),
    "build:openapi": (
        "posthog/api/*",
        "ee/api/*",
        "products/*/backend/api/*",
        "products/*/backend/presentation/*",
        "products/*/mcp/tools.yaml",
        "services/mcp/definitions/*",
    ),
    "build:grammar": ("posthog/hogql/grammar/*",),
    "build:taxonomy-json": ("posthog/taxonomy/*",),
    "build:products": ("products/*/frontend/*",),
    "build:skills": ("products/*/skills/*",),
    "build:schema-mcp": ("services/mcp/src/*",),
}


def _get_changed_files() -> set[str]:
    """Get all files changed on the current branch vs master, plus uncommitted changes."""
    changed: set[str] = set()

    # Branch changes vs merge-base with master
    try:
        merge_base = subprocess.check_output(
            ["git", "merge-base", "HEAD", "master"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        branch_diff = subprocess.check_output(
            ["git", "diff", "--name-only", f"{merge_base}...HEAD"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if branch_diff:
            changed.update(branch_diff.splitlines())
    except subprocess.CalledProcessError:
        pass

    # Working tree: staged + unstaged + untracked in one call
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain", "--no-renames"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in status.splitlines():
            if len(line) > 3:
                # Porcelain format: "XY filename" — 2-char status + space + path
                changed.add(line[3:])
    except subprocess.CalledProcessError:
        pass

    return changed


def _match_commands(changed_files: set[str]) -> list[str]:
    """Return commands whose trigger globs match any changed file."""
    return [
        cmd
        for cmd, globs in TRIGGERS.items()
        if any(fnmatch.fnmatch(path, glob) for path in changed_files for glob in globs)
    ]


@cli.command(name="build", help="Run code generation pipelines (smart change detection by default)")
@click.option("--force", is_flag=True, help="Rebuild all pipelines unconditionally")
@click.option("--dry-run", is_flag=True, help="Show what would be rebuilt without running")
@click.option("--list", "list_all", is_flag=True, help="List all available pipelines")
def build(force: bool, dry_run: bool, list_all: bool) -> None:
    """Unified build command with smart change detection."""
    if list_all:
        click.echo("Available build pipelines:\n")
        for cmd, globs in TRIGGERS.items():
            click.echo(f"  {cmd}")
            for glob in globs:
                click.echo(f"    {glob}")
        return

    if force:
        commands = list(TRIGGERS)
    else:
        changed = _get_changed_files()
        if not changed:
            click.echo("Nothing to rebuild -- no changes detected.")
            return
        commands = _match_commands(changed)
        if not commands:
            click.echo(f"Nothing to rebuild -- {len(changed)} changed file(s) don't match any build trigger.")
            return

    if dry_run:
        click.echo(f"Would build {len(commands)} pipeline(s):")
        for cmd in commands:
            click.echo(f"  {cmd}")
        return

    bin_hogli = str(REPO_ROOT / "bin" / "hogli")
    failed: list[str] = []
    for cmd in commands:
        click.secho(f"--- {cmd} ---", fg="blue", bold=True)
        result = subprocess.run([bin_hogli, cmd], cwd=REPO_ROOT)
        if result.returncode != 0:
            failed.append(cmd)

    click.echo()
    if failed:
        click.secho(f"Build completed with failures: {', '.join(failed)}", fg="red")
        raise SystemExit(1)
    else:
        click.secho("All pipelines completed successfully.", fg="green")
