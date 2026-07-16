"""GitHub App user tokens via the OAuth device flow, with an expiring 0600 cache.

General-purpose GitHub layer: mints a short-lived user access token for any
GitHub App (device flow, so no client secret) and caches it until it expires.
Which app to use, what the token is for, and how the session is presented to
the user belong to callers (see signing_session for the one current use).

Two deliberate properties of this layer: refresh tokens are never returned or
written (a cached six-month credential would defeat the point of short-lived
tokens), and a token response without an expiry is refused outright (it means
the app was registered without "Expire user authorization tokens").
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
from typing import Any, Final

import click
import requests

DEVICE_CODE_URL: Final = "https://github.com/login/device/code"
ACCESS_TOKEN_URL: Final = "https://github.com/login/oauth/access_token"
DEVICE_GRANT_TYPE: Final = "urn:ietf:params:oauth:grant-type:device_code"
REQUEST_TIMEOUT_SECONDS: Final = 10.0


@dataclass(frozen=True)
class GitHubApp:
    """A GitHub App identity (client IDs are public) plus where its minted user
    tokens are cached."""

    client_id: str
    token_cache_path: Path


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


def request_device_code(app: GitHubApp) -> DeviceAuthorization:
    payload = _github_login_post(DEVICE_CODE_URL, {"client_id": app.client_id})
    return DeviceAuthorization(
        device_code=str(payload["device_code"]),
        user_code=str(payload["user_code"]),
        verification_uri=str(payload["verification_uri"]),
        expires_in=int(payload["expires_in"]),
        interval=int(payload["interval"]),
    )


def poll_for_access_token(
    app: GitHubApp,
    device: DeviceAuthorization,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[str, int]:
    """Poll until the user authorizes on github.com; returns (access_token, expires_in seconds).

    GitHub reports pending states as HTTP 200 with an `error` field, so branch on
    the body, never the status code.
    """
    deadline = monotonic() + device.expires_in
    interval = float(device.interval)
    while True:
        if monotonic() >= deadline:
            raise click.ClickException("Timed out waiting for authorization. Start the login again.")
        sleep(interval)
        payload = _github_login_post(
            ACCESS_TOKEN_URL,
            {"client_id": app.client_id, "device_code": device.device_code, "grant_type": DEVICE_GRANT_TYPE},
        )
        error = payload.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = float(payload.get("interval", interval + 5))
            continue
        if error == "expired_token":
            raise click.ClickException("The device code expired (15 minutes). Start the login again.")
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


def write_cached_token(app: GitHubApp, token: str, expires_at: datetime) -> Path:
    app.token_cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"token": token, "expires_at": expires_at.isoformat(), "client_id": app.client_id})
    # 0600 from the first byte (no chmod-after-write window), then an atomic
    # rename so a concurrent reader never sees a half-written file.
    tmp_path = app.token_cache_path.with_suffix(".tmp")
    tmp_path.unlink(missing_ok=True)
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload.encode())
    finally:
        os.close(fd)
    os.replace(tmp_path, app.token_cache_path)
    return app.token_cache_path


def _read_cache(app: GitHubApp) -> tuple[str, datetime] | None:
    """The cached (token, expires_at), or None when missing, malformed, or minted
    by a different app (client ID changed since)."""
    try:
        payload = json.loads(app.token_cache_path.read_text())
        token = payload["token"]
        expires_at = datetime.fromisoformat(payload["expires_at"])
        if not isinstance(token, str) or not token or payload["client_id"] != app.client_id:
            return None
        if expires_at.tzinfo is None:
            return None
        return token, expires_at
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cached_token(app: GitHubApp, *, now: datetime | None = None, safety_margin: timedelta = timedelta()) -> str | None:
    """The cached token while it has more than `safety_margin` of validity left."""
    cache = _read_cache(app)
    if cache is None:
        return None
    token, expires_at = cache
    if (now or datetime.now(UTC)) >= expires_at - safety_margin:
        return None
    return token


def cached_token_expiry(app: GitHubApp) -> datetime | None:
    cache = _read_cache(app)
    return cache[1] if cache else None


def delete_cached_token(app: GitHubApp) -> bool:
    """Delete the cache; True when a cached token existed."""
    if app.token_cache_path.exists():
        app.token_cache_path.unlink()
        return True
    return False


def mint_user_token(app: GitHubApp, *, open_browser: bool = True) -> tuple[str, datetime]:
    """Interactive device-flow mint: prompts with the user code, waits for the
    authorization, caches the token, and returns (token, expires_at)."""
    device = request_device_code(app)
    click.echo(f"Open {device.verification_uri} and enter code: ", nl=False)
    click.secho(device.user_code, bold=True)
    if open_browser:
        webbrowser.open(device.verification_uri)
    click.echo("Waiting for authorization on github.com...")
    token, expires_in = poll_for_access_token(app, device)
    expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
    write_cached_token(app, token, expires_at)
    return token, expires_at
