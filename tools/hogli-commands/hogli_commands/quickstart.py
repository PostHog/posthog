"""PostHog development quickstart command."""

from __future__ import annotations

import click
from hogli.cli import cli


@cli.command(name="quickstart", help="Show getting started with PostHog development")
def quickstart() -> None:
    """Display essential commands for getting up and running."""
    click.echo("")
    click.echo(click.style("🚀 PostHog Development Quickstart", fg="green", bold=True))
    click.echo("")
    click.echo("Get PostHog running locally:")
    click.echo("")
    click.echo("  hogli start")
    click.echo("")
    click.echo("  That's it! Starts Docker, runs migrations, launches all services.")
    click.echo("  Opens http://localhost:8010 when ready.")
    click.echo("")
    click.echo("Optional:")
    click.echo("  hogli dev:setup               configure which services to run")
    click.echo("  hogli dev:demo-data           generate test data")
    click.echo("  hogli dev:reset               full reset & reload")
    click.echo("")
    click.echo("Common commands:")
    click.echo("  hogli format                  format all code")
    click.echo("  hogli lint                    run quality checks")
    click.echo("  hogli test:python <path>      run Python tests")
    click.echo("  hogli test:js <path>          run JS tests")
    click.echo("")
    click.echo("For full command list:")
    click.echo("  hogli --help")
    click.echo("")
