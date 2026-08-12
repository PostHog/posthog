from __future__ import annotations

import click

from .scaffold import bootstrap_service


@click.command(name="service:bootstrap", help="Scaffold a standalone Node.js service")
@click.argument("name")
@click.option("--dry-run", is_flag=True, help="Show what would be created without writing files")
@click.option("--force", is_flag=True, help="Overwrite files in an existing service")
def cmd_bootstrap(name: str, dry_run: bool, force: bool) -> None:
    bootstrap_service(name=name, dry_run=dry_run, force=force)
