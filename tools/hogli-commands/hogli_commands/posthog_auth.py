"""Shared PostHog API auth for hogli commands: a bearer token, without minting anything by hand.

Centralizes the one decision (how a hogli command gets an authenticated caller identity against
a PostHog host) so no command reimplements it, the way `github_auth` does for github.com.

    from hogli_commands import posthog_auth

    token = posthog_auth.token(scopes=("engineering_analytics:read",))

Three sources, in order:

1. ``POSTHOG_PERSONAL_API_KEY``, then ``POSTHOG_AUTH_HEADER`` (the name ``services/mcp`` has you
   export for mcp-remote). Either can be a literal line in ``.env.local``, which hogli loads on
   every invocation. Env wins so CI, containers, and an existing key keep working untouched.
2. A cached OAuth credential for that host, refreshed silently when the access token has aged out.
3. An interactive browser login, on a tty only.

The OAuth path asks the user for nothing but a click. PostHog's own authorization server does the
rest: the client self-registers via Dynamic Client Registration (RFC 7591), and the code comes back
to an ephemeral port on 127.0.0.1 (RFC 8252 native-app flow, with PKCE). There is deliberately no
personal API key in this path — a key would carry `<scope>:write` on every non-privileged scope,
where a token minted here carries exactly the scopes its caller asked for and is revocable from
Settings → Connected applications.

RFC 8628 device flow is NOT used: PostHog does not advertise that grant. For a machine with no
browser (a devbox over ssh), `login(open_browser=False)` prints the URL and reads the redirect back
instead — same flow, moved out of band.

Credentials are cached per host at ``~/.config/posthog/oauth/<host>.json`` with mode 0600,
alongside the registered client, so one login serves every hogli command on that host.

Nothing here opens a browser off a tty. A piped or agent-driven caller with no cached credential
gets ``AuthError`` carrying exit code 78 (sysexits ``EX_CONFIG``), so it can branch on the code
rather than on message text, and tell its human to run one command.
"""

from __future__ import annotations

import os
import sys
import json
import time
import base64
import hashlib
import secrets
import threading
import webbrowser
import http.server
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
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
    """Auth that could not be completed, phrased as something the reader can act on."""

    def __init__(self, message: str, *, exit_code: int = EXIT_NOT_CONFIGURED) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True, kw_only=True)
class Credential:
    """One host's cached OAuth state: the self-registered client, plus the tokens it minted.

    ``granted`` is what the server said it issued, not what was asked for, because /authorize
    clamps a request to the client's ceiling and a token can come back narrower than the ask.
    ``registered`` is that ceiling, so a caller needing a scope outside it needs a new client
    rather than just new consent.
    """

    host: str
    client_id: str
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    granted: tuple[str, ...] = ()
    registered: tuple[str, ...] = ()
    # What we asked the server to register, which is a superset of `registered` when the server
    # stripped something. Kept so a scope the server refuses is not re-requested on every call.
    requested: tuple[str, ...] = ()

    def is_fresh(self, *, now: float | None = None) -> bool:
        if self.expires_at is None:
            return True
        return (now if now is not None else time.time()) < self.expires_at - _EXPIRY_MARGIN_SECONDS

    def covers(self, scopes: Iterable[str]) -> bool:
        granted = set(self.granted)
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


def _cache_path(host: str) -> Path:
    """One file per host, named after it. Two hosts can hold credentials at once (us, eu, a local
    stack), and the name has to survive being a filename, so keep only unreserved characters."""
    slug = "".join(char if char.isalnum() else "-" for char in urlparse(host).netloc or host)
    return _CACHE_ROOT / f"{slug}.json"


def load(host: str = DEFAULT_HOST) -> Credential | None:
    """The cached credential for a host, or None when absent or unreadable.

    A cache file that can't be parsed is treated as absent rather than fatal: it is derived state,
    and re-authorizing is always available. A missing field is the same case — an older hogli may
    have written a narrower shape.
    """
    path = _cache_path(_normalize_host(host))
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    try:
        return Credential(
            host=str(raw["host"]),
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
    one, never a half-written one. The 0600 mode is set at open() rather than after, so the token
    is never briefly world-readable on disk.
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


def forget(host: str = DEFAULT_HOST) -> bool:
    """Drop a host's cached credential. True when there was one to drop.

    Local only: it does not revoke the grant server-side, which is done from Settings →
    Connected apps. Callers should say so rather than implying the token is now dead.
    """
    path = _cache_path(_normalize_host(host))
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def key_from_env() -> str | None:
    """A personal API key from the environment, if one is set.

    ``POSTHOG_AUTH_HEADER`` holds a whole ``Bearer <key>`` header value, so strip the scheme
    rather than sending it twice.
    """
    for var in KEY_ENV_VARS:
        raw = (os.environ.get(var) or "").strip()
        if not raw:
            continue
        # hogli's dotenv loader assigns the raw value, so a quoted `.env.local` line arrives with
        # its quotes attached and the `Bearer ` prefix no longer matches.
        if len(raw) > 1 and raw[0] == raw[-1] and raw[0] in "\"'":
            raw = raw[1:-1].strip()
        return raw.removeprefix("Bearer ").strip()
    return None


def _normalize_host(host: str) -> str:
    return host.rstrip("/")


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
        short = credential is not None and not credential.covers(scopes)
        missing = " ".join(scope for scope in scopes if scope not in (credential.granted if credential else ()))
        raise AuthError(
            (
                f"hogli is signed in to {host} but not for {missing}.\n"
                if short
                else f"hogli is not signed in to {host}.\n"
            )
            + f"  Run `hogli auth:posthog:login{f' --scope {missing}' if short else ''}` once. "
            "It opens a browser and asks for no API key.\n"
            f"  Or set {KEY_ENV_VARS[0]} for an unattended caller."
        )
    return login(scopes=scopes, host=host).access_token


def login(
    *,
    scopes: Sequence[str],
    host: str = DEFAULT_HOST,
    open_browser: bool = True,
) -> Credential:
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
    if existing is not None and set(wanted) <= set(existing.requested):
        client_id, registered, requested = existing.client_id, existing.registered, existing.requested
    else:
        # Carry forward what the old client could do, so authorizing for a new scope doesn't
        # silently narrow another command that was already working.
        requested = tuple(dict.fromkeys([*(existing.requested if existing else ()), *wanted]))
        client_id, registered = _register(host, requested)

    refused = [scope for scope in wanted if scope not in registered]
    if refused:
        # Refusing here leaves the registration unsaved, so retrying a bad scope name registers a
        # fresh client each time. Those rows carry no grant and never reach Connected applications,
        # which is why this is not worth making `access_token` optional to persist.
        # Known before the browser opens: /authorize clamps to the ceiling above, so consenting
        # would mint a token missing these and the failure would land after the user's click.
        raise AuthError(
            f"{host} will not grant {' '.join(refused)} to a self-registered client.\n"
            "  Check the scope name, and note that privileged scopes need an admin-registered app."
        )

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)

    with _CallbackServer() as server:
        url = f"{host}/oauth/authorize/?" + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": server.redirect_uri,
                "scope": " ".join(wanted),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        code = server.collect(url, state=state, open_browser=open_browser)
        redirect_uri = server.redirect_uri

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
    nothing had been cached.
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
    except AuthError:
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
    """One unauthenticated POST to an OAuth endpoint, with the failure phrased for a reader."""
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
        raise AuthError(f"{action} failed ({response.status_code}): {detail}")
    if not body:
        raise AuthError(f"{action} returned no object.")
    return body


class _Handler(http.server.BaseHTTPRequestHandler):
    """Captures the one redirect we are waiting for and ignores everything else.

    A browser also asks for /favicon.ico and may prefetch, so a handler that treated any request
    as the callback would end the wait on the wrong one. Only the registered path counts.
    """

    # Without this the read blocks forever on a socket that connects and sends nothing, and the
    # single-threaded server never returns to check the login deadline.
    timeout = 10.0

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != _REDIRECT_PATH:
            self.send_error(404)
            return
        self.server.query = parse_qs(parsed.query)  # type: ignore[attr-defined]
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
        self._server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self._server.query = None  # type: ignore[attr-defined]
        self.redirect_uri = f"http://127.0.0.1:{self._server.server_port}{_REDIRECT_PATH}"

    def __enter__(self) -> _CallbackServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self._server.server_close()

    def collect(self, url: str, *, state: str, open_browser: bool) -> str:
        """Serve until the redirect arrives, then return its authorization code."""
        # The URL is printed either way: it is the fallback when the browser doesn't open, and on a
        # remote box the listener is unreachable, so the address bar is where the code arrives.
        if open_browser:
            click.echo(f"Opening your browser to approve hogli. If nothing happens, open:\n  {url}", err=True)
            # On a thread, because `webbrowser.open` blocks until the browser exits for a
            # terminal-mode one (and for anything $BROWSER points at that doesn't detach). Opening
            # in the foreground would deadlock: the request it blocks on is the redirect only this
            # listener can serve.
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        else:
            click.echo(f"Open this URL to approve hogli:\n  {url}", err=True)
        return self._await_code(state=state)

    def _await_code(self, *, state: str) -> str:
        deadline = time.monotonic() + _LOGIN_TIMEOUT_SECONDS
        self._server.timeout = 1.0
        while self._server.query is None:  # type: ignore[attr-defined]
            if time.monotonic() > deadline:
                raise AuthError("Timed out waiting for the browser to come back.", exit_code=1)
            self._server.handle_request()
        query: dict[str, list[str]] = self._server.query  # type: ignore[attr-defined]
        return _code_from(query, state=state)


def _code_from(query: dict[str, list[str]], *, state: str) -> str:
    """The authorization code from a redirect's query, once it proves it answers our request."""
    if error := query.get("error"):
        described = (query.get("error_description") or [""])[0]
        raise AuthError(f"Authorization was refused: {error[0]}{f' ({described})' if described else ''}")
    # Without this the flow would accept a code from an authorization request we never made.
    if not secrets.compare_digest((query.get("state") or [""])[0], state):
        raise AuthError("The redirect carried the wrong state — start the login again.")
    code = (query.get("code") or [""])[0]
    if not code:
        raise AuthError("The redirect carried no authorization code.")
    return code


def redact(credential: Credential) -> Credential:
    """A copy safe to print: identifiers and scopes kept, secrets replaced.

    Exists so `auth:posthog:status` can render a credential without a caller having to remember
    which fields are secret.
    """
    return replace(
        credential, access_token="<redacted>", refresh_token="<redacted>" if credential.refresh_token else None
    )
