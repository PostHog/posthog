"""HTTP transport and browser-session auth shared by the support CLI scripts.

A tiny PostHog REST client: region/host resolution, a request wrapper that retries on rate
limits and 5xx, and session-cookie authentication for impersonated staff sessions. Both
scripts hit the same API surface, so keeping retry/backoff, defensive Retry-After parsing,
cookie scoping, and the acting-user safety check here means every script gets them.
`log_session_expiry` also lets a long batch run confirm the impersonated session's idle
timer is resetting as expected.
"""

import time
import argparse
import itertools
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from .console import confirm, log, printable
from .errors import PostHogScriptError

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0
RETRY_AFTER_MAX_SECONDS = 60.0
REGION_HOSTS = {"us": "https://us.posthog.com", "eu": "https://eu.posthog.com"}

# Sequential id per request_with_retries() call, so "rate limited" log lines can be told
# apart: a repeated id means the same request is still retrying, a new id means a different
# request just got rate-limited for the first time - not that the run is stuck.
_request_counter = itertools.count(1)


def resolve_host(value: str) -> str:
    """Map a region shorthand ('us'/'eu', any case) to its Cloud host; pass explicit hosts through."""
    return REGION_HOSTS.get(value.strip().lower(), value).rstrip("/")


def request_with_retries(
    session: requests.Session, method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs: Any
) -> requests.Response:
    """Issue a request, retrying on 429 (honoring Retry-After) and 5xx with backoff."""
    request_id = next(_request_counter)
    last_error = ""
    was_rate_limited = False
    for attempt in range(max_retries):
        try:
            response = session.request(method, url, timeout=60, **kwargs)
        except requests.RequestException as err:
            last_error = str(err)
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        if response.status_code == 429:
            was_rate_limited = True
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            default_wait = BACKOFF_BASE_SECONDS * 2**attempt
            raw_retry_after = response.headers.get("Retry-After")
            try:
                # Retry-After may be seconds or an HTTP-date; only the numeric form is honored
                retry_after = float(raw_retry_after) if raw_retry_after is not None else default_wait
            except ValueError:
                retry_after = default_wait
            retry_after = min(max(retry_after, 0.0), RETRY_AFTER_MAX_SECONDS)
            log(f"  [req {request_id}] rate limited, retrying in {retry_after:.0f}s...")
            time.sleep(retry_after)
            continue
        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        if was_rate_limited:
            log(f"  [req {request_id}] succeeded after being rate limited")
        return response
    raise PostHogScriptError(f"[req {request_id}] {method} {url} failed after {max_retries} attempts: {last_error}")


def run_hogql_query(
    session: requests.Session, host: str, project_id: str, query: str, max_retries: int = MAX_RETRIES
) -> list[list[Any]]:
    """Run a HogQL query through the query API and return its result rows."""
    response = request_with_retries(
        session,
        "POST",
        f"{host}/api/projects/{project_id}/query/",
        max_retries=max_retries,
        json={"query": {"kind": "HogQLQuery", "query": query}},
    )
    if response.status_code != 200:
        raise PostHogScriptError(f"HogQL query failed (HTTP {response.status_code}): {response.text[:500]}")
    return response.json()["results"]


def hogql_string_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def confirm_acting_user(email: str) -> None:
    """Make the operator type the session's email so the acting-as identity is conscious, not assumed."""
    log("Session auth acts as the browser session's logged-in user - including for read queries.")
    matched = confirm(
        "Enter that user's email to confirm you know who you're acting as: ",
        email,
        eof_message=(
            "Session auth requires interactively confirming the authenticated user; "
            "use a personal API key for non-interactive runs."
        ),
    )
    if not matched:
        raise PostHogScriptError(
            "That does not match the session's authenticated user - check whose session this is "
            "(e.g. the impersonated user in your browser) and rerun."
        )


def setup_session_auth(session: requests.Session, host: str, session_id: str) -> None:
    """Authenticate with a browser session cookie (works for impersonated staff sessions).

    Django session auth requires a CSRF token on unsafe methods, so fetch the CSRF cookie
    from the login page and mirror it into the X-CSRFToken header, with the host as Referer.
    Before anything runs - reads included - the operator must type the authenticated user's
    email to confirm they know who the session acts as.
    """
    parsed = urlparse(host)
    is_local = parsed.hostname in ("localhost", "127.0.0.1")
    if parsed.scheme != "https" and not is_local:
        raise PostHogScriptError(f"Refusing to send a session cookie to a non-HTTPS host: {host}")
    # Scope the cookie to this host (and require HTTPS) so requests never attaches the
    # session to another origin - e.g. via a mistyped --host or a cross-origin redirect.
    session.cookies.set("sessionid", session_id, domain=parsed.hostname, secure=not is_local)
    request_with_retries(session, "GET", f"{host}/login")
    csrf_token = session.cookies.get("posthog_csrftoken")
    if not csrf_token:
        raise PostHogScriptError(f"Could not obtain a CSRF cookie from {host}/login - is this a PostHog instance?")
    session.headers["X-CSRFToken"] = csrf_token
    session.headers["Referer"] = f"{host}/"

    me = request_with_retries(session, "GET", f"{host}/api/users/@me/")
    if me.status_code != 200:
        raise PostHogScriptError(
            f"Session auth failed (HTTP {me.status_code}) - is the sessionid cookie value current? "
            "Impersonated sessions expire when the impersonation ends or times out."
        )
    email = me.json().get("email")
    if not email:
        raise PostHogScriptError("Could not determine the session's authenticated user")
    confirm_acting_user(email)
    log(f"Authenticated via session as {email}")


def build_session(args: argparse.Namespace) -> requests.Session:
    """Build a Session authenticated per the standard --personal-api-key/--session-id flags."""
    session = requests.Session()
    if args.personal_api_key:
        session.headers["Authorization"] = f"Bearer {args.personal_api_key}"
    else:
        setup_session_auth(session, args.host, args.session_id)
    return session


def get_session_expiry(session: requests.Session, host: str) -> Optional[datetime]:
    """Return when the current impersonated session expires, or None if it isn't impersonated.

    Reads `is_impersonated_until` from /api/users/@me/ - the same value
    AutoLogoutImpersonateMiddleware enforces server-side. Always None for personal-API-key
    auth, which isn't impersonation.
    """
    response = request_with_retries(session, "GET", f"{host}/api/users/@me/", max_retries=1)
    if response.status_code != 200:
        return None
    expires_at = response.json().get("is_impersonated_until")
    return datetime.fromisoformat(expires_at) if expires_at else None


def log_session_expiry(session: requests.Session, host: str) -> None:
    """Log how much time an impersonated session has left; no-op for personal-API-key auth.

    Meant to be called from a batch-report checkpoint so a long run can confirm the idle
    timer is resetting as expected instead of silently counting down.
    """
    try:
        expires_at = get_session_expiry(session, host)
    except PostHogScriptError as err:
        log(f"  could not check session expiry: {printable(str(err))}")
        return
    if expires_at is None:
        return
    minutes_left = max(int((expires_at - datetime.now(UTC)).total_seconds() // 60), 0)
    log(f"  session active for {minutes_left}m more (expires {expires_at.isoformat()})")
