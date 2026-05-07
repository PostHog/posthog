"""Precheck handlers for hogli command lifecycle.

Precheck handlers run before composite commands execute (see ``steps:`` /
``prechecks:`` entries in hogli.yaml). They register against
``hogli.hooks.register_precheck`` at boot, and the heavy work happens lazily
inside the handler — keep this module light to import.
"""

from __future__ import annotations

import click
from hogli.hooks import register_precheck


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


register_precheck("migrations", _migrations_precheck)
