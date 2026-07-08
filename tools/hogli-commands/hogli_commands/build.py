"""Unified build command with smart change detection."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable

import click
from hogli.manifest import REPO_ROOT

from hogli_commands.change_detection import changed_files, matches_globs

# command -> file globs that should trigger it
TRIGGERS: dict[str, tuple[str, ...]] = {
    "build:schema": (
        "frontend/src/queries/schema/*",
        "posthog/schema_migrations/*",
    ),
    "build:openapi": (
        "posthog/api/*",
        "posthog/scopes.py",
        "ee/api/*",
        "products/*/backend/api/*",
        "products/*/backend/presentation/*",
        "products/*/backend/widget_specs/*",
        "products/*/mcp/tools.yaml",
        "services/mcp/definitions/*",
    ),
    "build:grammar": ("posthog/hogql/grammar/*",),
    "build:taxonomy-json": ("posthog/taxonomy/*",),
    "build:products": ("products/*/frontend/*",),
    "build:skills": ("products/*/skills/*",),
    "build:schema-mcp": ("services/mcp/src/*",),
}


def _match_commands(changed: Iterable[str]) -> list[str]:
    """Return build commands whose trigger globs match any changed file."""
    return [cmd for cmd, globs in TRIGGERS.items() if any(matches_globs(p, globs) for p in changed)]


@click.command(name="build", help="Run code generation pipelines (smart change detection by default)")
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
        changed = changed_files()
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
