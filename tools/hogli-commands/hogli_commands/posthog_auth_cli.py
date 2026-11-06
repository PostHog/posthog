"""`hogli posthog:*`, which signs hogli in to a PostHog host once, for every command.

The commands live here so `posthog_auth` stays a plain helper: a command that just needs a token
imports that module and picks up none of these.

    hogli posthog:login     # opens a browser; no API key to mint
    hogli posthog:status    # which host, which scopes, how long the token has left
    hogli posthog:logout    # revoke the grant, then drop the local credential
"""

from __future__ import annotations

import json
import time
from typing import NoReturn

import click

from hogli_commands import posthog_auth

# Enough to read CI health, which is what the first caller needs. A command wanting more passes its
# own scopes to `posthog_auth.token`, up to the ceiling the host publishes for hogli.
_DEFAULT_SCOPES = ("engineering_analytics:read",)

_HOST_OPTION = click.option(
    "--host",
    default=posthog_auth.DEFAULT_HOST,
    show_default=True,
    help="PostHog host to authenticate against (e.g. https://eu.posthog.com).",
)


def _fail(error: posthog_auth.AuthError) -> NoReturn:
    click.secho(error.message, fg="red", err=True)
    raise SystemExit(error.exit_code)


def _lifetime(expires_at: float | None) -> str:
    """What the access token has left, at the coarsest unit that still reads usefully.

    Tokens run to days, and minutes alone renders a week as "expires in 10079m", which a reader
    has to divide before it means anything.
    """
    if expires_at is None:
        return "no expiry reported"
    remaining = int(expires_at - time.time())
    if remaining <= 0:
        return "expired"
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if remaining >= size:
            return f"expires in {remaining // size}{unit}"
    return "expires in under a minute"


@click.command(name="posthog:login", help="Sign hogli in to PostHog in your browser.")
@_HOST_OPTION
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    help=f"API scope to request; repeatable. Defaults to {' '.join(_DEFAULT_SCOPES)}.",
)
def posthog_login(host: str, scopes: tuple[str, ...]) -> None:
    try:
        credential = posthog_auth.login(scopes=scopes or _DEFAULT_SCOPES, host=host)
    except posthog_auth.AuthError as exc:
        _fail(exc)
    click.secho(f"Signed in to {credential.host}.", fg="green")
    click.echo(f"  scopes  {' '.join(credential.granted) or '(none reported)'}")
    if found := posthog_auth.key_in_env():
        # Otherwise the login appears to have done nothing: every command reads the env var first.
        click.secho(
            f"\nNote: {found.variable} is set in your environment, and it wins over this credential.\n"
            f"Unset {found.variable} to use the browser login.",
            fg="yellow",
        )


@click.command(name="posthog:status", help="Show hogli's cached PostHog credential.")
@_HOST_OPTION
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table.")
def posthog_status(host: str, as_json: bool) -> None:
    host = host.rstrip("/")
    credential = posthog_auth.load(host)
    env_key = posthog_auth.key_from_env()
    # Both output shapes report the same verdict: a script gating on the exit code must not read
    # "configured" just because it asked for JSON.
    configured = bool(env_key or credential)
    if as_json:
        click.echo(
            json.dumps(
                {
                    "host": host,
                    "environment_key_set": bool(env_key),
                    "credential": posthog_auth.redact(credential).as_json() if credential else None,
                },
                indent=2,
            )
        )
        raise SystemExit(0 if configured else posthog_auth.EXIT_NOT_CONFIGURED)

    if found := posthog_auth.key_in_env():
        click.echo(f"environment    {found.variable} is set, and it wins over any cached credential")
    if credential is None:
        click.echo(f"credential     none cached for {host}. Run `hogli posthog:login`")
        raise SystemExit(0 if env_key else posthog_auth.EXIT_NOT_CONFIGURED)

    lifetime = _lifetime(credential.expires_at)
    click.echo(f"host           {credential.host}")
    click.echo(f"client         {credential.client_id}")
    click.echo(f"scopes         {' '.join(credential.granted) or '(none reported)'}")
    click.echo(f"access token   {lifetime}" + (", refreshable" if credential.refresh_token else ", not refreshable"))


@click.command(name="posthog:logout", help="Revoke and forget hogli's cached PostHog credential.")
@_HOST_OPTION
def posthog_logout(host: str) -> None:
    host = host.rstrip("/")
    result = posthog_auth.logout(host)
    if found := posthog_auth.key_in_env():
        # This is the command where "signed out" is acted on, and the key keeps every command signed in.
        click.secho(f"Note: {found.variable} is still set, and hogli keeps using it.", fg="yellow")
    if not result.forgotten:
        click.echo(f"No cached credential for {host}.")
        return
    if result.revoked:
        click.echo(f"Signed out of {host}. The token it held no longer works.")
        return
    click.echo(f"Forgot the cached credential for {host}.")
    if result.error:
        click.secho(result.error, fg="yellow", err=True)
    click.secho("The token may still work. Revoke it under Settings → Connected applications.", fg="yellow", err=True)
