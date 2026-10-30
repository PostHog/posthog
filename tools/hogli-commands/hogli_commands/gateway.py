"""`hogli gateway:token`, a short-lived AI gateway token for PostHog staff, and
`hogli gateway:status`, which reports how much of one is left.

hogli holds no PostHog credential for this. The staff member approves a PKCE challenge on the
developer mode settings page, the page hands a one-time code to a loopback port, and hogli
exchanges the code and its verifier for a token attributed to that staff member.
"""

from __future__ import annotations

import os
import sys
import json
import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit

import click
import requests

from hogli_commands import posthog_auth

_SETTINGS_PATH = "/settings/user-ai-gateway-dev-mode"
_EXCHANGE_PATH = "/api/ai_gateway/dev_tokens/cli_exchange/"
_STATUS_PATH = "/api/ai_gateway/dev_tokens/token_status/"
# Checked in order; the first value that is a phe_ token wins, so a real provider key is skipped.
_TOKEN_ENV_VARS = ("POSTHOG_GATEWAY_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
_HTTP_TIMEOUT_SECONDS = 30.0
# An approved code plus its verifier is a token, so the CLI only sends them to hosts staff
# actually approve on. Local dev hosts match on any port.
_ALLOWED_HOSTS = ("https://us.posthog.com", "https://eu.posthog.com")
_LOCAL_HOSTNAMES = ("localhost", "127.0.0.1")


@click.command(name="gateway:token", help="Get a short-lived AI gateway token after you approve it in your browser.")
@click.option(
    "--host",
    default=posthog_auth.DEFAULT_HOST,
    show_default=True,
    help="PostHog host that mints the token (e.g. https://eu.posthog.com).",
)
@click.option(
    "--allow-any-host",
    is_flag=True,
    help="Skip the --host allowlist. Only use this for a host you run yourself.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the full token response as JSON.")
def gateway_token(host: str, allow_any_host: bool, as_json: bool) -> None:
    host = host.rstrip("/") if allow_any_host else _allowed_host(host)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    def approval_url(port: int) -> str:
        return f"{host}{_SETTINGS_PATH}?" + urlencode(
            {"cli_challenge": challenge, "cli_port": port, "cli_state": state}
        )

    try:
        code = posthog_auth.approve_in_browser(approval_url, state=state)
    except posthog_auth.AuthError as error:
        click.secho(error.message, fg="red", err=True)
        raise SystemExit(error.exit_code)

    minted = _exchange(host, code=code, verifier=verifier)
    if as_json:
        click.echo(json.dumps(minted))
        return
    # Only the token goes to stdout, so `$(hogli gateway:token)` captures it alone.
    click.echo(minted["token"])
    click.echo(
        f"\nThe token expires at {minted['expires_at']} and can spend up to ${minted['cap_usd']}.",
        err=True,
    )


@click.command(name="gateway:status", help="Show how much budget a developer mode token has left.")
@click.option(
    "--host",
    default=posthog_auth.DEFAULT_HOST,
    show_default=True,
    help="PostHog host that minted the token (e.g. https://eu.posthog.com).",
)
@click.option(
    "--allow-any-host",
    is_flag=True,
    help="Skip the --host allowlist. Only use this for a host you run yourself.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the full status response as JSON.")
def gateway_status(host: str, allow_any_host: bool, as_json: bool) -> None:
    host = host.rstrip("/") if allow_any_host else _allowed_host(host)
    token = _find_token()
    status = _post(host, _STATUS_PATH, {"token": token}, expected=200, action="token status lookup")
    if as_json:
        click.echo(json.dumps(status))
        return
    if status["status"] != "live":
        click.echo(f"The token is {status['status']}.")
        return
    if status.get("remaining_usd") is None:
        click.echo(f"The token is live, with a ${status['cap_usd']} cap. The gateway did not report what is left.")
    else:
        # Four places, because single calls cost fractions of a cent and two would show an untouched cap.
        remaining = float(status["remaining_usd"])
        spent = float(status["cap_usd"]) - remaining
        click.echo(f"${remaining:.4f} of ${status['cap_usd']} left (${spent:.4f} spent).")
    click.echo(f"The token expires at {status['expires_at']}.")


def _find_token() -> str:
    """Reads the token from stdin or the environment, never argv, so it stays out of shell history."""
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if piped:
            if not piped.startswith("phe_"):
                raise click.UsageError("stdin does not hold a phe_ token.")
            return piped
    for name in _TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value.startswith("phe_"):
            return value
    raise click.UsageError(f"No phe_ token found. Pipe one on stdin or set one of {', '.join(_TOKEN_ENV_VARS)}.")


def _allowed_host(host: str) -> str:
    try:
        parts = urlsplit(host.strip())
        port = parts.port
    except ValueError:
        parts, port = None, None
    if parts is not None and parts.hostname:
        hostname = parts.hostname.lower()
        if parts.scheme == "http" and hostname in _LOCAL_HOSTNAMES:
            return f"http://{hostname}" + (f":{port}" if port else "")
        if parts.scheme == "https" and port in (None, 443):
            origin = f"https://{hostname}"
            if origin in _ALLOWED_HOSTS:
                return origin
    allowed = ", ".join([*_ALLOWED_HOSTS, "http://localhost:<port>", "http://127.0.0.1:<port>"])
    raise click.BadParameter(
        f"{host} is not an allowed host. Allowed values: {allowed}. Pass --allow-any-host to use another host.",
        param_hint="'--host'",
    )


def _exchange(host: str, *, code: str, verifier: str) -> dict[str, Any]:
    return _post(host, _EXCHANGE_PATH, {"code": code, "code_verifier": verifier}, expected=201, action="token exchange")


def _post(host: str, path: str, payload: dict[str, str], *, expected: int, action: str) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{host}{path}",
            json=payload,
            timeout=_HTTP_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as error:
        raise click.ClickException(f"Could not reach {host}: {error}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != expected or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else None
        raise click.ClickException(f"{host} refused the {action} ({response.status_code}): {detail or response.text}")
    return body
