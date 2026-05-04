"""Developer Click commands for PostHog workflows.

This is the extension point for adding new Click commands to hogli.
Add your @cli.command() decorated functions here as an alternative to shell scripts.

They auto-register with hogli and appear in `hogli --help` automatically.

Example:
    ```python
    import click
    from hogli.cli import cli

    @cli.command(name="my:command", help="Does something useful")
    @click.argument('path', type=click.Path())
    @click.option('--flag', is_flag=True, help='Enable feature')
    def my_command(path, flag):
        '''Command implementation.'''
        # Your Python logic here
        click.echo(f"Processing {path}")
    ```

Guidelines:
- Use Click decorators for arguments and options
- Import cli group from hogli.cli (the framework in tools/hogli/)
- Name commands with colons for grouping (e.g., 'test:python', 'db:migrate')
- Add helpful docstrings - they become the command help text
- Prefer Python Click commands over shell scripts for better type safety

For simple shell commands or bin script delegation, use hogli.yaml instead.
"""

from __future__ import annotations

import os
import sys
import time as _time
import subprocess
import configparser
from pathlib import Path
from typing import Any

import click
from hogli.hooks import register_post_command_hook, register_precheck, register_telemetry_properties
from hogli.manifest import REPO_ROOT
from hogli.telemetry import _load_config, _save_config

# Side-effect imports: these modules use @cli.command() decorators that register
# commands with the CLI group when imported. The imports appear unused but are required.
from . import (  # noqa: F401
    build,
    devbox,
    doctor,
    hints,
    metabase,
    migrations,
    product,
    quickstart,
    telemetry_commands,
    test_runner,
)
from .devenv import cli as devenv_cli  # noqa: F401
from .migrations import _compute_migration_diff, _get_cached_migration

# ---------------------------------------------------------------------------
# Precheck handlers -- registered with the hogli framework
# ---------------------------------------------------------------------------


def _migrations_precheck(check: dict, yes: bool) -> bool | None:
    """Check for orphaned migrations before starting services."""
    try:
        diff = _compute_migration_diff()

        if diff.orphaned:
            click.echo()
            click.secho("\u26a0\ufe0f  Orphaned migrations detected!", fg="yellow", bold=True)
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
        click.secho(f"\u26a0\ufe0f  Could not check migrations: {e}", fg="yellow", err=True)

    return None


register_precheck("migrations", _migrations_precheck)


# ---------------------------------------------------------------------------
# Telemetry property hooks -- PostHog-specific environment properties
# ---------------------------------------------------------------------------


def _infer_process_manager(command: str | None) -> str | None:
    pm = os.environ.get("HOGLI_PROCESS_MANAGER")
    if pm:
        return os.path.basename(pm)
    if command == "start":
        return "mprocs" if "--mprocs" in sys.argv[2:] else "phrocs"
    return None


_POSTHOG_DEV_CACHE_TTL_SECONDS = 30 * 86400  # 30 days


def _check_email_domain() -> bool:
    """Fallback: check if git user.email ends with @posthog.com."""
    parser = configparser.RawConfigParser()
    try:
        parser.read([Path.home() / ".gitconfig", REPO_ROOT / ".git" / "config"])
        email = parser.get("user", "email", fallback="")
        return email.endswith("@posthog.com")
    except Exception:
        return False


def _check_github_org_membership() -> bool | None:
    """Use ``gh api`` to check PostHog org membership. Returns None if gh is unavailable."""
    try:
        result = subprocess.run(
            ["gh", "api", "/user/memberships/orgs/PostHog", "--silent"],
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return None


def _is_posthog_dev() -> bool:
    """Check if the user is a PostHog GitHub org member.

    Uses ``gh api`` to check org membership, caching the boolean result in
    the telemetry config for 30 days.  Falls back to a git email domain
    check when ``gh`` is unavailable or unauthenticated.
    """
    config = _load_config()
    cached = config.get("is_posthog_org_member")
    checked_at = config.get("org_check_timestamp", 0.0)

    if cached is not None and (_time.time() - checked_at) < _POSTHOG_DEV_CACHE_TTL_SECONDS:
        return cached

    is_member = _check_github_org_membership()
    if is_member is None:
        is_member = _check_email_domain()

    config["is_posthog_org_member"] = is_member
    config["org_check_timestamp"] = _time.time()
    _save_config(config)
    return is_member


def _posthog_telemetry_properties(command: str | None = None) -> dict[str, Any]:
    return {
        "has_devenv_config": (REPO_ROOT / ".posthog" / ".generated" / "mprocs.yaml").exists(),
        "in_flox": os.environ.get("FLOX_ENV") is not None,
        "is_worktree": (REPO_ROOT / ".git").is_file(),
        "is_posthog_dev": _is_posthog_dev(),
        "process_manager": _infer_process_manager(command),
    }


register_telemetry_properties(_posthog_telemetry_properties)


# ---------------------------------------------------------------------------
# Post-command hooks -- run after telemetry flush on every invocation
# ---------------------------------------------------------------------------


def _show_hints_post_command(command: str | None, exit_code: int) -> None:
    """Print a contextual hint on successful commands."""
    if exit_code == 0:
        hints.maybe_show_hint(command)


register_post_command_hook(_show_hints_post_command)
