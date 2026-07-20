"""The commit-signing session: an 8-hour GitHub App token for `git:publish-signed`.

Special-purpose layer over github_app_auth. `hogli git:signing-session` mints a
user token from the org-registered hogli-publisher app and caches it; while the
session is active, unattended agents publish GitHub-signed (Verified) commits
without a human present.

Security posture, stated honestly: the cache file is mode 0600 but any process
running as the same user can read it. The improvement over the gh CLI token is
blast radius, not secrecy: the token dies within 8 hours, carries only the app's
Contents/Workflows permissions on repos the installation covers, and the org can
revoke every token at once by uninstalling the app. No refresh token ever touches
disk (github_app_auth discards it), so a session cannot be silently extended.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

import click

from hogli_commands.github_app_auth import (
    GitHubApp,
    cached_token,
    cached_token_expiry,
    delete_cached_token,
    mint_user_token,
)
from hogli_commands.github_auth import env_token, gh_cli_token

# Public identifier of the hogli-publisher GitHub App (client IDs are not
# secrets). Empty until the app is registered on the PostHog org; the env var
# lets forks and early testers point at their own app.
GITHUB_APP_CLIENT_ID: Final = ""
CLIENT_ID_ENV_VAR: Final = "HOGLI_GITHUB_APP_CLIENT_ID"
TOKEN_CACHE_PATH: Final = Path.home() / ".config" / "posthog" / "github-app-token.json"
# A multi-commit publish can take minutes; never let one start nearly expired.
EXPIRY_SAFETY_MARGIN: Final = timedelta(minutes=10)

AuthMode = Literal["app", "env", "gh"]
AuthChoice = Literal["auto", "app", "env", "gh"]


def _configured_app() -> GitHubApp | None:
    client_id = os.environ.get(CLIENT_ID_ENV_VAR) or GITHUB_APP_CLIENT_ID
    if not client_id:
        return None
    return GitHubApp(client_id=client_id, token_cache_path=TOKEN_CACHE_PATH)


def _require_app() -> GitHubApp:
    app = _configured_app()
    if app is None:
        raise click.ClickException(
            f"The hogli-publisher GitHub App is not registered yet; set {CLIENT_ID_ENV_VAR} to use another app's client ID."
        )
    return app


def session_token() -> str | None:
    """The active session's token, with enough validity left for a full publish."""
    app = _configured_app()
    if app is None:
        return None
    return cached_token(app, safety_margin=EXPIRY_SAFETY_MARGIN)


def token_for_mode(mode: AuthChoice) -> tuple[str, AuthMode] | None:
    """The token a publish should use, with the mode it came from.

    `auto` prefers the app token so an exported long-lived token can't silently
    bypass the 8h hardening once a human has minted one; explicit modes never
    fall through to another source.
    """
    if mode in ("auto", "app"):
        if token := session_token():
            return token, "app"
        if mode == "app":
            return None
    if mode in ("auto", "env"):
        if token := env_token():
            return token, "env"
        if mode == "env":
            return None
    if token := gh_cli_token():
        return token, "gh"
    return None


def run_device_login(*, force: bool = False, open_browser: bool = True) -> None:
    app = _require_app()
    if not force and cached_token(app, safety_margin=EXPIRY_SAFETY_MARGIN):
        expiry = cached_token_expiry(app)
        assert expiry is not None
        hours, minutes = divmod(int((expiry - datetime.now(UTC)).total_seconds()) // 60, 60)
        click.echo(
            f"Signing session active until {expiry.astimezone():%H:%M} ({hours}h{minutes:02d}m left). "
            "Use --force to restart it."
        )
        return
    _token, expires_at = mint_user_token(app, open_browser=open_browser)
    hours = int((expires_at - datetime.now(UTC)).total_seconds()) // 3600
    click.secho(f"Signing session started; valid until {expires_at.astimezone():%H:%M} (~{hours}h).", fg="green")


def _end_session() -> None:
    app = _configured_app()
    if app is not None and delete_cached_token(app):
        click.echo("Signing session ended (cached token deleted).")
    else:
        click.echo("No active signing session.")
    click.echo("Revoke past authorizations at https://github.com/settings/apps/authorizations")


@click.command(name="git:signing-session")
@click.option("--force", is_flag=True, help="Restart the session even if a valid token is cached.")
@click.option("--no-open", is_flag=True, help="Don't open the verification page in a browser.")
@click.option("--end", "end_session", is_flag=True, help="End the session by deleting the cached token.")
def git_signing_session(force: bool, no_open: bool, end_session: bool) -> None:
    """Start an 8-hour signing session for unattended publishing.

    Mints a short-lived GitHub App user token via the device flow and caches
    it for `hogli git:publish-signed`. Run this once before stepping away;
    unattended agents can then publish GitHub-signed commits until it expires.
    The session is not scoped to one repository: while it is active, publishes
    work on every repo the hogli-publisher installation covers.
    When a session is already active, prints the time remaining instead.
    There is no refresh token on disk, so start a new session (roughly once
    per workday) when it expires.
    """
    if end_session:
        _end_session()
        return
    run_device_login(force=force, open_browser=not no_open)
