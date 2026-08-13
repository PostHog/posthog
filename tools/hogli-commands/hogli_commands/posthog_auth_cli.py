"""`hogli auth:posthog:*`, which signs hogli in to a PostHog host once, for every command.

Separate from `posthog_auth` so importing the shared token helper costs no click machinery: a
command that just needs a token imports the module, not this surface.

    hogli auth:posthog:login     # opens a browser; no API key to mint
    hogli auth:posthog:status    # which host, which scopes, how long the token has left
    hogli auth:posthog:logout    # drop the local credential
"""

from __future__ import annotations

import json
import time
from typing import NoReturn

import click

from hogli_commands import posthog_auth

# Enough to read CI health, which is what asks for a login today. Not a ceiling: a command needing
# more passes its own scopes to `posthog_auth.token`, which re-authorizes on demand.
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


@click.command(name="auth:posthog:login", help="Sign hogli in to PostHog in your browser.")
@_HOST_OPTION
@click.option(
    "--scope",
    "scopes",
    multiple=True,
    help=f"API scope to request; repeatable. Defaults to {' '.join(_DEFAULT_SCOPES)}.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    help="Print the URL instead of opening it, for a machine with no browser (a devbox over ssh).",
)
def posthog_login(host: str, scopes: tuple[str, ...], no_browser: bool) -> None:
    try:
        credential = posthog_auth.login(
            scopes=scopes or _DEFAULT_SCOPES,
            host=host,
            open_browser=not no_browser,
        )
    except posthog_auth.AuthError as exc:
        _fail(exc)
    click.secho(f"Signed in to {credential.host}.", fg="green")
    click.echo(f"  scopes  {' '.join(credential.granted) or '(none reported)'}")
    if key := posthog_auth.key_from_env():
        # Otherwise the login appears to have done nothing: every command reads the env var first.
        click.secho(
            f"\nNote: {key[:8]}... is set in your environment, and env wins over this credential.\n"
            "Unset it to use the browser login.",
            fg="yellow",
        )


@click.command(name="auth:posthog:status", help="Show hogli's cached PostHog credential.")
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
        click.echo(f"environment    {found[0]} is set, and it wins over any cached credential")
    if credential is None:
        click.echo(f"credential     none cached for {host}. Run `hogli auth:posthog:login`")
        raise SystemExit(0 if env_key else posthog_auth.EXIT_NOT_CONFIGURED)

    remaining = None if credential.expires_at is None else int(credential.expires_at - time.time())
    if remaining is None:
        lifetime = "no expiry reported"
    elif remaining > 0:
        lifetime = f"expires in {remaining // 60}m"
    else:
        lifetime = "expired"
    click.echo(f"host           {credential.host}")
    click.echo(f"client         {credential.client_id}")
    click.echo(f"scopes         {' '.join(credential.granted) or '(none reported)'}")
    click.echo(f"access token   {lifetime}" + (", refreshable" if credential.refresh_token else ", not refreshable"))


@click.command(name="auth:posthog:logout", help="Forget hogli's cached PostHog credential.")
@_HOST_OPTION
def posthog_logout(host: str) -> None:
    host = host.rstrip("/")
    if posthog_auth.forget(host):
        click.echo(f"Forgot the cached credential for {host}.")
        click.echo("Revoke the grant itself under Settings → Connected apps.", err=True)
    else:
        click.echo(f"No cached credential for {host}.")
