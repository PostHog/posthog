"""`hogli gateway:token`, a short-lived AI gateway token for PostHog staff.

hogli holds no PostHog credential for this. The staff member approves a PKCE challenge on the
developer mode settings page, the page hands a one-time code to a loopback port, and hogli
exchanges the code and its verifier for a token attributed to that staff member.
"""

from __future__ import annotations

import json
import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import click
import requests

from hogli_commands import posthog_auth

_SETTINGS_PATH = "/settings/user-ai-gateway-dev-mode"
_EXCHANGE_PATH = "/api/ai_gateway/dev_tokens/cli_exchange/"
_HTTP_TIMEOUT_SECONDS = 30.0


@click.command(name="gateway:token", help="Get a short-lived AI gateway token after you approve it in your browser.")
@click.option(
    "--host",
    default=posthog_auth.DEFAULT_HOST,
    show_default=True,
    help="PostHog host that mints the token (e.g. https://eu.posthog.com).",
)
@click.option("--json", "as_json", is_flag=True, help="Print the full token response as JSON.")
def gateway_token(host: str, as_json: bool) -> None:
    host = host.rstrip("/")
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


def _exchange(host: str, *, code: str, verifier: str) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{host}{_EXCHANGE_PATH}",
            json={"code": code, "code_verifier": verifier},
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise click.ClickException(f"Could not reach {host}: {error}")
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code != 201 or not isinstance(body, dict):
        detail = body.get("detail") if isinstance(body, dict) else None
        raise click.ClickException(
            f"{host} refused the token exchange ({response.status_code}): {detail or response.text}"
        )
    return body
