"""Shared PostHog API auth for hogli commands, the way `github_auth` does for github.com.

    from hogli_commands import posthog_auth

    token = posthog_auth.token(scopes=("engineering_analytics:read",))

Three sources, in order:

1. ``POSTHOG_PERSONAL_API_KEY``, then ``POSTHOG_AUTH_HEADER`` (the name ``services/mcp`` has you
   export for mcp-remote). Either can be a literal line in ``.env.local``, which hogli loads on
   every invocation. Env wins so CI, containers, and an existing key keep working untouched.
2. A cached OAuth credential for that host, refreshed silently when the access token has aged out.
3. An interactive browser login, on a tty only.

The browser path is the RFC 8252 native-app flow: the client self-registers via Dynamic Client
Registration (RFC 7591), and the code comes back to an ephemeral port on 127.0.0.1 with PKCE.
RFC 8628 device flow is not used because PostHog does not advertise that grant. A login always
prints the URL as well as opening it, and accepts the redirect typed back in, so it also finishes
on a machine whose browser lives somewhere else.

Credentials are cached per host at ``~/.config/posthog/oauth/<host>.json`` with mode 0600,
alongside the registered client, so one login serves every hogli command on that host. Dropping a
credential revokes it at the server first, since a deleted file leaves a refresh token that still
mints access tokens for anyone holding a copy.

Nothing here opens a browser off a tty. A piped or agent-driven caller with no cached credential
gets ``AuthError`` carrying exit code 78 (sysexits ``EX_CONFIG``), so it can branch on the code
rather than on message text.
"""

from __future__ import annotations

import os
import sys
import json
import time
import queue
import base64
import hashlib
import secrets
import threading
import webbrowser
import http.server
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import click
import requests

DEFAULT_HOST = "https://us.posthog.com"

# sysexits.h EX_CONFIG. Distinct from 1 so a caller can tell "you have not set this up" from
# "the command ran and the answer is bad" without parsing prose.
EXIT_NOT_CONFIGURED = 78

KEY_ENV_VARS = ("POSTHOG_PERSONAL_API_KEY", "POSTHOG_AUTH_HEADER")

_CACHE_ROOT = Path.home() / ".config" / "posthog" / "oauth"

_CLIENT_NAME = "hogli"
# Registered without a port: RFC 8252 §7.3 requires the server to allow any port on a loopback
# redirect, so one registration covers whichever ephemeral port we get. 127.0.0.1 rather than
# localhost because django-oauth-toolkit's port exemption lists the literal addresses.
_REDIRECT_URI = "http://127.0.0.1/callback"
_REDIRECT_PATH = "/callback"

# Refresh this far before the access token actually expires, so a slow request can't start on a
# valid token and arrive on an expired one.
_EXPIRY_MARGIN_SECONDS = 120.0

_LOGIN_TIMEOUT_SECONDS = 300.0
_HTTP_TIMEOUT_SECONDS = 30.0

_DONE_PAGE = b"""<!doctype html><meta charset=utf-8><title>hogli</title>
<body style="font:14px -apple-system,sans-serif;padding:3rem;text-align:center">
<h1 style="font-size:1.1rem">You're signed in</h1><p>Close this tab and return to your terminal.</p>
"""


class AuthError(Exception):
    def __init__(self, message: str, *, exit_code: int = EXIT_NOT_CONFIGURED) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True, kw_only=True)
class Credential:
    """One host's cached OAuth state: the self-registered client, plus the tokens it minted.

    Three scope tuples, narrowest first, because /authorize clamps a request to the client's
    ceiling. ``granted`` is what the server said it issued, which can be narrower than the ask.
    ``registered`` is that ceiling, so a caller needing a scope outside it needs a new client
    rather than new consent. ``requested`` is what we asked to register, a superset of
    ``registered`` when the server stripped something, kept so a refused scope is not re-requested
    on every call.
    """

    host: str
    client_id: str
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    granted: tuple[str, ...] = ()
    registered: tuple[str, ...] = ()
    requested: tuple[str, ...] = ()

    def is_fresh(self, *, now: float | None = None) -> bool:
        if self.expires_at is None:
            return True
        return (now if now is not None else time.time()) < self.expires_at - _EXPIRY_MARGIN_SECONDS

    def covers(self, scopes: Iterable[str]) -> bool:
        granted = set(self.granted)
        # An empty `granted` means the server reported no scopes, which is "unknown" rather than
        # "none", so it satisfies any ask.
        return not granted or set(scopes) <= granted

    def as_json(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "client_id": self.client_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "granted": list(self.granted),
            "registered": list(self.registered),
            "requested": list(self.requested),
        }


@dataclass(frozen=True, kw_only=True)
class Logout:
    """What a logout did. ``forgotten`` without ``revoked`` means the token still works."""

    forgotten: bool
    revoked: bool
    error: str | None = None


@dataclass(frozen=True, kw_only=True)
class EnvironmentKey:
    """A personal API key found in the environment, and the variable it came from."""

    variable: str
    key: str = field(repr=False)


def _normalize_host(host: str) -> str:
    return host.rstrip("/")


def _cache_path(host: str) -> Path:
    """One file per host, so us, eu and a local stack can hold credentials at once.

    Only unreserved characters survive into the name, since the host has to be a valid filename.
    The scheme is part of the name because http://host and https://host are different origins
    holding different grants, and a name built from the netloc alone would hand one's token to
    the other.
    """
    parsed = urlparse(host)
    origin = f"{parsed.scheme}-{parsed.netloc}" if parsed.netloc else host
    slug = "".join(char if char.isalnum() else "-" for char in origin)
    return _CACHE_ROOT / f"{slug}.json"


def load(host: str = DEFAULT_HOST) -> Credential | None:
    """The cached credential for a host, or None when absent, unreadable, or for another host.

    An unparseable file, or one missing a field because an older hogli wrote a narrower shape, is
    treated as absent rather than fatal: it is derived state, and re-authorizing is always there.
    """
    host = _normalize_host(host)
    try:
        raw = json.loads(_cache_path(host).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("host") != host:
        # Hosts differing only by URL path share a filename, which the slug cannot carry. A miss
        # sends the caller to a login; serving the other host's token would send its credential
        # to the wrong server.
        return None
    try:
        return Credential(
            host=host,
            client_id=str(raw["client_id"]),
            access_token=str(raw["access_token"]),
            refresh_token=raw.get("refresh_token"),
            expires_at=raw.get("expires_at"),
            granted=tuple(raw.get("granted") or ()),
            registered=tuple(raw.get("registered") or ()),
            requested=tuple(raw.get("requested") or raw.get("registered") or ()),
        )
    except (KeyError, TypeError):
        return None


def save(credential: Credential) -> None:
    """Persist a credential, readable only by its owner.

    Written to a temp file and renamed so a concurrent reader sees either the old file or the new
    one, never a half-written one. Mode 0600 is set at open() rather than after, so the token is
    never briefly world-readable on disk.
    """
    path = _cache_path(credential.host)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(credential.as_json(), handle)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def logout(host: str = DEFAULT_HOST) -> Logout:
    """Revoke a host's credential at the server, then drop it locally.

    Revocation goes first because the file is the only record of the token: dropping it first
    strands a live refresh token nobody can name. A failed revocation still drops the file, and
    reports that the grant is live so the caller can say where to finish it off.
    """
    host = _normalize_host(host)
    credential = load(host)
    path = _cache_path(host)
    existed = credential is not None or path.exists()
    failure: str | None = None
    if credential is not None:
        try:
            revoke(credential)
        except AuthError as exc:
            failure = exc.message
    path.unlink(missing_ok=True)
    return Logout(forgotten=existed, revoked=credential is not None and failure is None, error=failure)


def _revoke_superseded(credential: Credential) -> None:
    """Revoke a credential a fresh login replaced. Warns rather than raising: the login worked."""
    try:
        revoke(credential)
    except AuthError as exc:
        click.secho(
            f"Could not revoke the previous credential for {credential.host}: {exc.message}", fg="yellow", err=True
        )
        click.secho("It is still live. Revoke it under Settings → Connected apps.", fg="yellow", err=True)


def revoke(credential: Credential) -> None:
    """Tell the server to drop the grant, so a copy of the token stops working.

    The refresh token goes when there is one, since it outlives the access token and mints more,
    and django-oauth-toolkit's `RefreshToken.revoke` takes the paired access token with it.
    """
    hint = "refresh_token" if credential.refresh_token else "access_token"
    revoked = credential.refresh_token or credential.access_token
    _send(
        f"{credential.host}/oauth/revoke/",
        # A public client authenticates on client_id alone, with no secret to present.
        form_body={"token": revoked, "token_type_hint": hint, "client_id": credential.client_id},
        action="Revoking the credential",
    )


def key_in_env() -> EnvironmentKey | None:
    """The personal API key set in the environment, with its variable, or None when neither is set.

    Carries both so `status` does not re-derive which variable won, since a second scan could
    disagree with this one about whether a whitespace-only value counts. ``POSTHOG_AUTH_HEADER``
    holds a whole ``Bearer <key>`` header value, so the scheme is stripped rather than sent twice.
    """
    for var in KEY_ENV_VARS:
        raw = (os.environ.get(var) or "").strip()
        if not raw:
            continue
        # hogli's dotenv loader assigns the raw value, so a quoted `.env.local` line arrives with
        # its quotes attached and the `Bearer ` prefix no longer matches.
        if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1].strip()
        return EnvironmentKey(variable=var, key=raw.removeprefix("Bearer ").strip())
    return None


def key_from_env() -> str | None:
    """Just the key, for callers that do not care which variable carried it."""
    found = key_in_env()
    return found.key if found else None


def token(
    *,
    scopes: Sequence[str],
    host: str = DEFAULT_HOST,
    interactive: bool | None = None,
) -> str:
    """A bearer token for ``host``, good for ``scopes``. The one function callers need.

    ``interactive`` defaults to whether stdin is a tty. Off, a missing or scope-short credential
    raises rather than trying to open a browser: a piped caller cannot answer a consent screen,
    and blocking for five minutes on a login nobody can see is worse than failing fast.
    """
    host = _normalize_host(host)
    if key := key_from_env():
        return key

    credential = load(host)
    if credential is not None and credential.covers(scopes):
        if credential.is_fresh():
            return credential.access_token
        if refreshed := _refresh(credential):
            save(refreshed)
            return refreshed.access_token

    if interactive is None:
        interactive = sys.stdin.isatty()
    if not interactive:
        if credential is not None and not credential.covers(scopes):
            missing = " ".join(scope for scope in scopes if scope not in credential.granted)
            headline = f"hogli is signed in to {host} but not for {missing}."
            command = f"`hogli auth:posthog:login --scope {missing}`"
        else:
            headline = f"hogli is not signed in to {host}."
            command = "`hogli auth:posthog:login`"
        raise AuthError(
            f"{headline}\n"
            f"  Run {command} once. It opens a browser and asks for no API key.\n"
            f"  Or set {KEY_ENV_VARS[0]} for an unattended caller."
        )
    return login(scopes=scopes, host=host).access_token


def login(*, scopes: Sequence[str], host: str = DEFAULT_HOST) -> Credential:
    """Run the browser authorization flow and cache the result.

    Reuses the cached client registration when its ceiling already covers ``scopes``; a caller
    asking for something outside it needs a new client, since /authorize clamps to the ceiling and
    would otherwise hand back a token quietly missing the scope that was asked for.
    """
    host = _normalize_host(host)
    wanted = tuple(dict.fromkeys(scopes))
    if not wanted:
        raise AuthError("A login needs at least one scope to ask for.", exit_code=1)

    existing = load(host)
    # Compared against what was asked for, never against what came back. A scope the server strips
    # is absent from `registered` forever, so keying off that re-registers on every attempt and
    # leaves a dead OAuth client plus a live grant behind each time.
    superseded: Credential | None = None
    if existing is not None and set(wanted) <= set(existing.requested):
        client_id, registered, requested = existing.client_id, existing.registered, existing.requested
    else:
        # Carry forward what the old client could do, so authorizing for a new scope doesn't
        # silently narrow another command that was already working.
        requested = tuple(dict.fromkeys([*(existing.requested if existing else ()), *wanted]))
        client_id, registered = _register(host, requested)
        # Revoked below, once the replacement exists: overwriting the file would otherwise leave
        # its refresh token live and unnameable.
        superseded = existing

    refused = [scope for scope in wanted if scope not in registered]
    if refused:
        # Checked before the browser opens because /authorize clamps to the ceiling above, so
        # consenting would mint a token missing these and fail after the user's click. The cost is
        # an unsaved client registration per retry, which carries no grant and needs no revoking.
        raise AuthError(
            f"{host} will not grant {' '.join(refused)} to a self-registered client.\n"
            "  Check the scope name, and note that privileged scopes need an admin-registered app."
        )

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    with _CallbackServer() as server:
        redirect_uri = server.redirect_uri
        url = f"{host}/oauth/authorize/?" + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "scope": " ".join(wanted),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        code = server.collect(url, state=state)

    credential = _exchange(
        host,
        client_id=client_id,
        code=code,
        verifier=verifier,
        redirect_uri=redirect_uri,
        registered=registered,
        requested=requested,
        asked=wanted,
    )
    save(credential)
    if superseded is not None:
        _revoke_superseded(superseded)
    if not credential.covers(wanted):
        # The ceiling check above cannot see a narrowing that happens at consent time, so this is
        # the backstop. Returning here would hand back a token quietly missing what was asked for,
        # and the failure would surface later as an unactionable 403 on a scope check.
        missing = " ".join(scope for scope in wanted if scope not in credential.granted)
        raise AuthError(f"{host} granted a token without {missing}.")
    return credential


def _register(host: str, scopes: Sequence[str]) -> tuple[str, tuple[str, ...]]:
    """Self-register a public client via RFC 7591, returning its id and granted ceiling.

    The server strips scopes a self-registering client may not have and echoes back what it
    stored, so read the ceiling off the response rather than assuming the request survived.
    """
    payload = {
        "client_name": _CLIENT_NAME,
        "redirect_uris": [_REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": " ".join(scopes),
    }
    body = _post(f"{host}/oauth/register/", json_body=payload, action="Registering hogli")
    client_id = body.get("client_id")
    if not client_id:
        raise AuthError(f"{host} registered no client_id for hogli.")
    granted = tuple(str(body.get("scope") or " ".join(scopes)).split())
    return str(client_id), granted


def _exchange(
    host: str,
    *,
    client_id: str,
    code: str,
    verifier: str,
    redirect_uri: str,
    registered: tuple[str, ...],
    requested: tuple[str, ...],
    asked: tuple[str, ...],
) -> Credential:
    body = _post(
        f"{host}/oauth/token/",
        form_body={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
        action="Exchanging the authorization code",
    )
    return _credential_from(
        body,
        host=host,
        client_id=client_id,
        registered=registered,
        requested=requested,
        # RFC 6749 §5.1 makes `scope` optional when it matches the request, so an omission means
        # the ask was granted whole. Recording nothing instead would read as "scopes unknown".
        fallback_granted=asked,
    )


def _refresh(credential: Credential) -> Credential | None:
    """A renewed credential, or None when the refresh token is spent.

    None rather than raising: an expired or revoked grant is an ordinary end of life, and the
    caller's next step (log in again, or fail with the not-configured code) is the same as if
    nothing had been cached. A transient failure raises instead, because the grant may still be
    good and "not signed in" would be false.
    """
    if not credential.refresh_token:
        return None
    try:
        body = _post(
            f"{credential.host}/oauth/token/",
            form_body={
                "grant_type": "refresh_token",
                "refresh_token": credential.refresh_token,
                "client_id": credential.client_id,
            },
            action="Refreshing the access token",
        )
    except AuthError as exc:
        # Only a definitive OAuth refusal (a 4xx such as invalid_grant) proves the grant spent.
        # A network failure or a 5xx says nothing about it, so the error surfaces as itself
        # rather than sending the caller through a needless re-login.
        if exc.exit_code != EXIT_NOT_CONFIGURED:
            raise
        return None
    return _credential_from(
        body,
        host=credential.host,
        client_id=credential.client_id,
        registered=credential.registered,
        requested=credential.requested,
        # Refresh-token rotation is optional; keep the working one when the server reissues none.
        fallback_refresh=credential.refresh_token,
        fallback_granted=credential.granted,
    )


def _credential_from(
    body: dict[str, Any],
    *,
    host: str,
    client_id: str,
    registered: tuple[str, ...],
    requested: tuple[str, ...],
    fallback_refresh: str | None = None,
    fallback_granted: tuple[str, ...] = (),
) -> Credential:
    access_token = body.get("access_token")
    if not access_token:
        raise AuthError(f"{host} returned no access token.")
    expires_in = body.get("expires_in")
    granted = tuple(str(body["scope"]).split()) if body.get("scope") else fallback_granted
    return Credential(
        host=host,
        client_id=client_id,
        access_token=str(access_token),
        refresh_token=str(body.get("refresh_token") or fallback_refresh or "") or None,
        expires_at=time.time() + float(expires_in) if expires_in else None,
        granted=granted,
        registered=registered,
        requested=requested,
    )


def _post(
    url: str,
    *,
    action: str,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One unauthenticated POST to an OAuth endpoint whose answer is the object it returns."""
    body = _send(url, action=action, json_body=json_body, form_body=form_body)
    if not body:
        raise AuthError(f"{action} returned no object.")
    return body


def _send(
    url: str,
    *,
    action: str,
    json_body: dict[str, Any] | None = None,
    form_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One unauthenticated POST to an OAuth endpoint. RFC 7009 revocation answers 200 with no body."""
    try:
        response = requests.post(url, json=json_body, data=form_body, timeout=_HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise AuthError(f"{action} could not reach {url}: {exc}", exit_code=1) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    # Before any .get(): a proxy or load balancer can answer with valid JSON that is not an object,
    # and an AttributeError here escapes the AuthError handling every caller relies on.
    if not isinstance(body, dict):
        body = {}
    if response.status_code >= 400:
        # OAuth errors are `error` / `error_description`; DRF's are `detail`.
        detail = body.get("error_description") or body.get("error") or body.get("detail") or response.text[:200]
        # A 5xx means the server or a proxy in front of it is unhealthy, not that anything here
        # is set up wrong, so it carries the plain failure code rather than EX_CONFIG.
        code = 1 if response.status_code >= 500 else EXIT_NOT_CONFIGURED
        raise AuthError(f"{action} failed ({response.status_code}): {detail}", exit_code=code)
    return body


class _RedirectServer(http.server.HTTPServer):
    """Carries the redirect's query from the handler back to the waiting login."""

    query: dict[str, list[str]] | None = None


class _Handler(http.server.BaseHTTPRequestHandler):
    """Captures the one redirect we are waiting for and ignores everything else.

    A browser also asks for /favicon.ico and may prefetch, so a handler that treated any request
    as the callback would end the wait on the wrong one. Only the registered path counts.
    """

    server: _RedirectServer

    # Without this the read blocks forever on a socket that connects and sends nothing, and the
    # single-threaded server never returns to check the login deadline.
    timeout = 10.0

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != _REDIRECT_PATH:
            self.send_error(404)
            return
        self.server.query = parse_qs(parsed.query)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(_DONE_PAGE)))
        self.end_headers()
        self.wfile.write(_DONE_PAGE)

    def log_message(self, *args: Any) -> None:
        """Silence the default stderr access log; it is noise around a browser handoff."""


class _CallbackServer:
    """A loopback listener for one authorization redirect.

    Bound to port 0, so the OS picks a free port and two logins can never collide. RFC 8252 §7.3
    obliges the server to accept whichever port that is against the portless registered URI.
    """

    def __init__(self) -> None:
        self._server = _RedirectServer(("127.0.0.1", 0), _Handler)
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_port}{_REDIRECT_PATH}"

    def __enter__(self) -> _CallbackServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.server_close()

    def collect(self, url: str, *, state: str) -> str:
        """Serve until the redirect arrives, then return its authorization code."""
        # Printed as well as opened, because a devbox over ssh is indistinguishable from a laptop
        # here, and there the open does nothing.
        click.echo(f"Approve hogli in your browser:\n  {url}", err=True)
        # On a thread because `webbrowser.open` blocks until the browser exits for a terminal-mode
        # browser, or anything $BROWSER points at that doesn't detach. In the foreground it would
        # deadlock on the redirect only this listener can serve.
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        return self._await_code(state=state)

    def _await_code(self, *, state: str) -> str:
        deadline = time.monotonic() + _LOGIN_TIMEOUT_SECONDS
        self._server.timeout = 1.0
        pasted = _pasted_redirects()
        while self._server.query is None:
            if pasted is not None and not pasted.empty():
                return _code_from(pasted.get(), state=state)
            if time.monotonic() > deadline:
                raise AuthError("Timed out waiting for the browser to come back.", exit_code=1)
            self._server.handle_request()
        return _code_from(self._server.query, state=state)


def _pasted_redirects() -> queue.Queue[dict[str, list[str]]] | None:
    """Redirects typed back in, or None when there is no terminal to type at.

    A browser on another machine cannot reach this listener, so its redirect fails and the code
    exists only in the address bar of a page that never loaded. Read alongside the listener rather
    than instead of it, because which one the redirect reaches cannot be detected from here.
    """
    if not sys.stdin.isatty():
        return None
    click.echo("If your browser is on another machine, paste the address it lands on:", err=True)
    queued: queue.Queue[dict[str, list[str]]] = queue.Queue()
    threading.Thread(target=_read_redirect, args=(queued,), daemon=True).start()
    return queued


def _read_redirect(queued: queue.Queue[dict[str, list[str]]]) -> None:
    """Read lines until one carries an authorization redirect, queueing its query."""
    while line := sys.stdin.readline():
        pasted = line.strip()
        # The address may arrive whole or as the query alone, depending on what the user selected.
        query = parse_qs(urlparse(pasted).query or pasted)
        if query.get("code") or query.get("error"):
            queued.put(query)
            return
        if pasted:
            click.echo("That address carried no authorization code. Paste the whole thing, including ?code=.", err=True)


def _code_from(query: dict[str, list[str]], *, state: str) -> str:
    """The authorization code from a redirect's query, once it proves it answers our request."""
    if error := query.get("error"):
        described = (query.get("error_description") or [""])[0]
        raise AuthError(f"Authorization was refused: {error[0]}{f' ({described})' if described else ''}")
    # Without this the flow would accept a code from an authorization request we never made.
    if not secrets.compare_digest((query.get("state") or [""])[0], state):
        raise AuthError("The redirect carried the wrong state. Start the login again.")
    code = (query.get("code") or [""])[0]
    if not code:
        raise AuthError("The redirect carried no authorization code.")
    return code


def redact(credential: Credential) -> Credential:
    """A copy safe to print, so a caller rendering a credential need not track which fields are secret."""
    return replace(
        credential, access_token="<redacted>", refresh_token="<redacted>" if credential.refresh_token else None
    )
