"""Short-lived GitHub App tokens for publishing signed commits, via the OAuth device flow.

`hogli github:login` mints an 8-hour user access token from the org-registered
hogli-publisher GitHub App (device flow, no client secret) and caches it at
~/.config/posthog/github-app-token.json. `hogli git:publish-signed` prefers this
token over the gh CLI's long-lived OAuth token.

Security posture, stated honestly: the cache file is mode 0600 but any process
running as the same user can read it. The improvement over the gh CLI token is
blast radius, not secrecy: the token dies within 8 hours, carries only the app's
Contents/Workflows permissions on repos the installation covers, and the org can
revoke every token at once by uninstalling the app. The refresh token GitHub
returns is deliberately discarded; caching a six-month credential would recreate
the long-lived-token problem this flow exists to avoid.
"""

from __future__ import annotations

import os
import json
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final, Literal

import click
import requests

from hogli_commands.github_auth import env_token, gh_cli_token

# Public identifier of the hogli-publisher GitHub App (client IDs are not
# secrets). Empty until the app is registered on the PostHog org; the env var
# lets forks and early testers point at their own app.
GITHUB_APP_CLIENT_ID: Final = ""
CLIENT_ID_ENV_VAR: Final = "HOGLI_GITHUB_APP_CLIENT_ID"

DEVICE_CODE_URL: Final = "https://github.com/login/device/code"
ACCESS_TOKEN_URL: Final = "https://github.com/login/oauth/access_token"
DEVICE_GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:device_code"
TOKEN_CACHE_PATH: Final = Path.home() / ".config" / "posthog" / "github-app-token.json"
# A multi-commit publish can take minutes; never let one start nearly expired.
EXPIRY_SAFETY_MARGIN: Final = timedelta(minutes=10)
REQUEST_TIMEOUT_SECONDS: Final = 10.0

AuthMode = Literal["app", "env", "gh"]
AuthChoice = Literal["auto", "app", "env", "gh"]


def _client_id() -> str:
    if client_id := os.environ.get(CLIENT_ID_ENV_VAR):
        return client_id
    if GITHUB_APP_CLIENT_ID:
        return GITHUB_APP_CLIENT_ID
    raise click.ClickException(
        f"The hogli-publisher GitHub App is not registered yet; set {CLIENT_ID_ENV_VAR} to use another app's client ID."
    )


@dataclass(frozen=True)
class DeviceAuthorization:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


def _github_login_post(url: str, data: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(
            url, data=data, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as err:
        raise click.ClickException(f"GitHub device flow request failed: {err}") from err
    if not isinstance(payload, dict):
        raise click.ClickException("GitHub device flow request returned an unexpected payload.")
    return payload


def request_device_code() -> DeviceAuthorization:
    payload = _github_login_post(DEVICE_CODE_URL, {"client_id": _client_id()})
    return DeviceAuthorization(
        device_code=str(payload["device_code"]),
        user_code=str(payload["user_code"]),
        verification_uri=str(payload["verification_uri"]),
        expires_in=int(payload["expires_in"]),
        interval=int(payload["interval"]),
    )


def poll_for_access_token(
    device: DeviceAuthorization,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, int]:
    """Poll until the user authorizes on github.com; returns (access_token, expires_in seconds).

    GitHub reports pending states as HTTP 200 with an `error` field, so branch on
    the body, never the status code. The refresh token in the success payload is
    dropped on purpose (see module docstring).
    """
    deadline = monotonic() + device.expires_in
    interval = float(device.interval)
    while True:
        if monotonic() >= deadline:
            raise click.ClickException("Timed out waiting for authorization. Run `hogli github:login` again.")
        sleep(interval)
        payload = _github_login_post(
            ACCESS_TOKEN_URL,
            {"client_id": _client_id(), "device_code": device.device_code, "grant_type": DEVICE_GRANT_TYPE},
        )
        error = payload.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = float(payload.get("interval", interval + 5))
            continue
        if error == "expired_token":
            raise click.ClickException("The device code expired (15 minutes). Run `hogli github:login` again.")
        if error == "access_denied":
            raise click.ClickException("Authorization was declined on github.com.")
        if error:
            raise click.ClickException(f"Device flow failed: {payload.get('error_description', error)}")
        if "expires_in" not in payload:
            raise click.ClickException(
                "GitHub returned a non-expiring token. The app must have 'Expire user "
                "authorization tokens' enabled; ask an org admin to turn it on."
            )
        return str(payload["access_token"]), int(payload["expires_in"])


def _write_cached_token(token: str, expires_at: datetime) -> Path:
    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"token": token, "expires_at": expires_at.isoformat(), "client_id": _client_id()})
    # 0600 from the first byte (no chmod-after-write window), then an atomic
    # rename so a concurrent publish never reads a half-written file.
    tmp_path = TOKEN_CACHE_PATH.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload.encode())
    finally:
        os.close(fd)
    os.replace(tmp_path, TOKEN_CACHE_PATH)
    return TOKEN_CACHE_PATH


def _read_cache() -> tuple[str, datetime] | None:
    """The cached (token, expires_at), or None when missing, malformed, or minted
    by a different app (client ID changed since)."""
    expected_client_id = os.environ.get(CLIENT_ID_ENV_VAR) or GITHUB_APP_CLIENT_ID
    try:
        payload = json.loads(TOKEN_CACHE_PATH.read_text())
        token = payload["token"]
        expires_at = datetime.fromisoformat(payload["expires_at"])
        if not isinstance(token, str) or not token or payload["client_id"] != expected_client_id:
            return None
        if expires_at.tzinfo is None:
            return None
        return token, expires_at
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached_token(now: datetime | None = None) -> str | None:
    """The cached app token while it has comfortably more than the safety margin left."""
    cache = _read_cache()
    if cache is None:
        return None
    token, expires_at = cache
    if (now or datetime.now(UTC)) >= expires_at - EXPIRY_SAFETY_MARGIN:
        return None
    return token


def cached_token_expiry() -> datetime | None:
    cache = _read_cache()
    return cache[1] if cache else None


def token_for_mode(mode: AuthChoice) -> tuple[str, AuthMode] | None:
    """The token a publish should use, with the mode it came from.

    `auto` prefers the app token so an exported long-lived token can't silently
    bypass the 8h hardening once a human has minted one; explicit modes never
    fall through to another source.
    """
    if mode in ("auto", "app"):
        if token := cached_token():
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
    if not force and cached_token() is not None:
        expiry = cached_token_expiry()
        assert expiry is not None
        click.echo(f"Already logged in; token valid until {expiry.astimezone():%H:%M}. Use --force to re-mint.")
        return
    device = request_device_code()
    click.echo(f"Open {device.verification_uri} and enter code: ", nl=False)
    click.secho(device.user_code, bold=True)
    if open_browser:
        webbrowser.open(device.verification_uri)
    click.echo("Waiting for authorization on github.com...")
    token, expires_in = poll_for_access_token(device)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    _write_cached_token(token, expires_at)
    click.secho(f"Logged in. Token valid until {expires_at.astimezone():%H:%M} (~{expires_in // 3600}h).", fg="green")


@click.command(name="github:login")
@click.option("--force", is_flag=True, help="Re-mint even if a valid token is cached.")
@click.option("--no-open", is_flag=True, help="Don't open the verification page in a browser.")
def github_login(force: bool, no_open: bool) -> None:
    """Mint an 8-hour GitHub App token for unattended signed publishing.

    Runs GitHub's device flow against the hogli-publisher app and caches the
    token for `hogli git:publish-signed`. Run this once before stepping away;
    there is no refresh token on disk, so log in again (roughly once per
    workday) when it expires.
    """
    run_device_login(force=force, open_browser=not no_open)


@click.command(name="github:status")
def github_status() -> None:
    """Show which GitHub auth `git:publish-signed` would use."""
    resolved = token_for_mode("auto")
    if resolved is None:
        raise click.ClickException("No GitHub auth available. Run `hogli github:login` or `gh auth login`.")
    _token, mode = resolved
    if mode == "app":
        expiry = cached_token_expiry()
        assert expiry is not None
        remaining = expiry - datetime.now(UTC)
        hours, minutes = divmod(int(remaining.total_seconds()) // 60, 60)
        click.echo(f"app token (hogli-publisher), valid for {hours}h{minutes:02d}m")
    elif mode == "env":
        click.echo("env token (GH_TOKEN/GITHUB_TOKEN)")
    else:
        click.echo("gh CLI token (long-lived; run `hogli github:login` for an 8h app token)")


@click.command(name="github:logout")
def github_logout() -> None:
    """Delete the cached GitHub App token."""
    if TOKEN_CACHE_PATH.exists():
        TOKEN_CACHE_PATH.unlink()
        click.echo("Deleted the cached app token.")
    else:
        click.echo("No cached app token.")
    click.echo("Revoke authorizations at https://github.com/settings/apps/authorizations")
