"""Authenticate to internal Metabase via SSO and run queries against it.

Production Metabase sits behind ALB Cognito OAuth, so callers need both the
ALB session cookies (`ph_int_auth-0`, `ph_int_auth-1`) and the Metabase
application cookies (`metabase.SESSION`, `metabase.DEVICE`). API keys alone
won't pass the ALB.

Workflow:
    hogli metabase:login --region us|eu|dev     # opens browser, captures cookies
    hogli metabase:databases --region us|eu|dev # list databases with current IDs
    hogli metabase:query --region us|eu|dev \\  # run SQL against /api/dataset
        --database-id <id> < query.sql
    hogli metabase:cookie --region us|eu|dev    # print cached cookie header (humans)

Cookies are cached at ~/.config/posthog/metabase/cookie-{region} with mode 0600.
The `query` command reads the cookie internally so callers never see it —
prefer it over `cookie` when automation is running the query.
"""

from __future__ import annotations

import os
import sys
import json
import time
import plistlib
import functools
import subprocess
import webbrowser
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import click

LOGIN_TIMEOUT_SECONDS: float = 180.0
LOGIN_POLL_INTERVAL_SECONDS: float = 1.0

# Per-browser profile-cookie locations. Each entry is (loader_name, base_directory).
# We glob `<base>/*/Cookies` to discover every profile (Default, Profile 1, ...).
_HOME = Path.home()
_CHROMIUM_PROFILE_ROOTS: dict[str, list[Path]] = {
    "chrome": [_HOME / "Library/Application Support/Google/Chrome"],
    "chromium": [_HOME / "Library/Application Support/Chromium"],
    "brave": [_HOME / "Library/Application Support/BraveSoftware/Brave-Browser"],
    "arc": [_HOME / "Library/Application Support/Arc/User Data"],
    "dia": [_HOME / "Library/Application Support/Dia/User Data"],
}
_FIREFOX_ROOT: Path = _HOME / "Library/Application Support/Firefox"

REGIONS: dict[str, str] = {
    "us": "metabase.prod-us.posthog.dev",
    "eu": "metabase.prod-eu.posthog.dev",
    "dev": "metabase.dev.posthog.dev",
}
REQUIRED_COOKIES: tuple[str, ...] = (
    "metabase.SESSION",
    "metabase.DEVICE",
    "ph_int_auth-0",
    "ph_int_auth-1",
)
SUPPORTED_BROWSERS: tuple[str, ...] = ("chrome", "chromium", "brave", "arc", "dia", "firefox", "safari")
CACHE_DIR: Path = Path.home() / ".config" / "posthog" / "metabase"

_HTTPS_HANDLER_BUNDLE_IDS: dict[str, str] = {
    "org.mozilla.firefox": "firefox",
    "com.google.chrome": "chrome",
    "org.chromium.chromium": "chromium",
    "com.brave.browser": "brave",
    "company.thebrowser.browser": "arc",
    "com.apple.safari": "safari",
}


def _cookie_path(region: str) -> Path:
    return CACHE_DIR / f"cookie-{region}"


def _format_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


@functools.lru_cache(maxsize=1)
def _default_https_browser() -> str | None:
    """Return the supported browser name registered as the system's https handler.

    Only implemented for macOS, via LaunchServices. Any failure to run or parse
    `defaults export` — missing binary, unreadable plist, unknown bundle id — falls
    back to `None` so the caller keeps today's fixed browser order. Getting the
    default wrong only costs one extra decrypt; it never blocks login.
    """
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["defaults", "export", "com.apple.LaunchServices/com.apple.launchservices.secure", "-"],
            capture_output=True,
            check=True,
            timeout=5.0,
        )
        handlers = plistlib.loads(result.stdout).get("LSHandlers", [])
    except Exception:
        return None

    for handler in handlers:
        if not isinstance(handler, dict) or handler.get("LSHandlerURLScheme") != "https":
            continue
        bundle_id = handler.get("LSHandlerRoleAll") or handler.get("LSHandlerRoleViewer")
        if isinstance(bundle_id, str):
            return _HTTPS_HANDLER_BUNDLE_IDS.get(bundle_id.lower())
    return None


def _ordered_browsers(browser: str | None) -> tuple[str, ...]:
    """Browsers to scan for cookies, default https handler first when known.

    Without this, a machine with several browsers installed decrypts (and
    Keychain-prompts for) every one of them in a fixed order before reaching
    whichever browser actually holds the Metabase session. Only reorders —
    every supported browser is still tried if the default one comes up empty.
    """
    if browser is not None:
        return (browser,)
    default = _default_https_browser()
    if default is None or default not in SUPPORTED_BROWSERS:
        return SUPPORTED_BROWSERS
    return (default, *(name for name in SUPPORTED_BROWSERS if name != default))


def _enumerate_cookie_files(browser: str | None) -> list[tuple[str, Path]]:
    """Return (loader_name, cookie_file_path) pairs for every browser profile to try.

    Chromium-family browsers (Chrome, Brave, Chromium, Arc, Dia) keep a `Cookies`
    SQLite db per profile (`Default`, `Profile 1`, ...). We glob each profile
    directory so users with multiple profiles (work + personal) don't have to
    care which one they logged in with.

    Firefox and Safari fall back to the default `browser_cookie3` loader.
    """
    targets: list[tuple[str, Path]] = []
    for name in _ordered_browsers(browser):
        if name in _CHROMIUM_PROFILE_ROOTS:
            for root in _CHROMIUM_PROFILE_ROOTS[name]:
                if not root.exists():
                    continue
                for cookies_db in sorted(root.glob("*/Cookies")):
                    targets.append((name, cookies_db))
        else:
            targets.append((name, Path()))
    return targets


def _iter_cookie_candidates(
    domain: str,
    browser: str | None,
    seen_warnings: set[str] | None = None,
) -> Iterator[dict[str, str]]:
    """Yield one complete REQUIRED_COOKIES set per readable browser profile, in scan order.

    A profile that doesn't hold every required cookie is skipped rather than
    merged with another profile's set — cookie values from two different
    logins don't add up to a valid session. This is a generator, so a caller
    that stops once an earlier candidate validates never decrypts (or
    Keychain-prompts for) a later profile.

    Decrypting Chromium cookies on macOS triggers a one-time Keychain prompt
    per profile; users who pick "Always allow" won't see it again.

    `seen_warnings`, when passed, dedupes load errors across repeated calls
    (a polling loop) so the same warning doesn't reprint every interval.
    """
    try:
        import browser_cookie3
    except ImportError as exc:
        raise click.ClickException(
            "browser-cookie3 is not installed. Run `uv sync` to install dev dependencies.",
        ) from exc

    if browser is not None and browser not in SUPPORTED_BROWSERS:
        raise click.ClickException(f"Unsupported browser: {browser}")

    def dia(domain_name: str, cookie_file: str | None = None) -> Iterable:
        # Dia has no browser_cookie3 loader; it's Chromium-based but decrypts
        # its cookie DB with its own Keychain entry, so build one from ChromiumBased.
        return browser_cookie3.ChromiumBased(
            browser="Dia",
            cookie_file=cookie_file,
            domain_name=domain_name,
            osx_cookies=[],
            osx_key_service="Dia Safe Storage",
            osx_key_user="Dia",
        ).load()

    targets = _enumerate_cookie_files(browser)
    found_candidate = False
    errors: list[str] = []
    for loader_name, cookie_file in targets:
        loader = dia if loader_name == "dia" else getattr(browser_cookie3, loader_name, None)
        if loader is None:
            continue
        kwargs: dict = {"domain_name": domain}
        if cookie_file != Path():
            kwargs["cookie_file"] = str(cookie_file)
        try:
            jar = loader(**kwargs)
        except Exception as exc:
            errors.append(f"{loader_name} ({cookie_file or 'default'}): {exc}")
            continue
        source_cookies: dict[str, str] = {}
        for cookie in jar:
            if cookie.name in REQUIRED_COOKIES and cookie.value:
                source_cookies[cookie.name] = cookie.value
        if all(name in source_cookies for name in REQUIRED_COOKIES):
            found_candidate = True
            yield source_cookies

    if not found_candidate and errors:
        new_errors = errors if seen_warnings is None else [e for e in errors if e not in seen_warnings]
        if seen_warnings is not None:
            seen_warnings.update(errors)
        if new_errors:
            click.echo("\n".join(f"  warn: {e}" for e in new_errors), err=True)


def _find_valid_candidate(
    domain: str,
    browser: str | None,
    seen_warnings: set[str] | None = None,
    rejected_headers: set[str] | None = None,
) -> tuple[str | None, bool]:
    """Try each cookie candidate against Metabase in order; return (header, any_candidate).

    `header` is the first candidate's cookie header the server accepts, or
    `None` if none did. `rejected_headers`, when passed, skips re-checking a
    header the server already outright rejected, without stopping the scan —
    an expired session in an earlier profile must not block a valid one in a
    later profile, on this call or a repeated one. A header the server hasn't
    confirmed or rejected (a network blip, a 5xx from the load balancer) is
    never added to `rejected_headers`, so it gets retried on the next call.
    """
    any_candidate = False
    for candidate in _iter_cookie_candidates(domain, browser, seen_warnings):
        any_candidate = True
        header = _format_cookie_header(candidate)
        if rejected_headers is not None and header in rejected_headers:
            continue
        result = _probe_cookie(domain, header)
        if result is True:
            return header, any_candidate
        if result is False and rejected_headers is not None:
            rejected_headers.add(header)
    return None, any_candidate


def _secure_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically at mode 0600.

    `Path.write_text` goes through open(2) with the process umask, so the file
    is briefly world-readable before we could chmod it. `os.open` with an
    explicit mode dodges the TOCTOU window — callers storing session cookies
    or query results must use this instead of `write_text`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, content.encode())
    finally:
        os.close(fd)


def _write_cookie_file(region: str, cookie_header: str) -> Path:
    path = _cookie_path(region)
    _secure_write(path, cookie_header)
    return path


def _read_cookie_file(region: str) -> str | None:
    path = _cookie_path(region)
    if not path.exists():
        return None
    return path.read_text().strip()


def _probe_cookie(domain: str, cookie_header: str, timeout: float = 5.0) -> bool | None:
    """Hit /api/user/current and classify the response into three states.

    `True`: the session is valid. `False`: the server rejected it outright (a
    redirect back to SSO, 401, 403) — this cookie will not become valid
    later. `None`: a transport failure or a transient status (5xx, 429,
    anything else unexpected) — inconclusive, so a caller should retry
    rather than treat the cookie as dead.
    """
    import requests

    try:
        response = requests.get(
            f"https://{domain}/api/user/current",
            headers={"Cookie": cookie_header},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        return None

    if response.status_code == 200:
        return True
    if response.status_code in (401, 403) or 300 <= response.status_code < 400:
        return False
    return None


def _check_cookie(domain: str, cookie_header: str, timeout: float = 5.0) -> bool:
    """Confirm the cookie is currently valid. `None` (inconclusive) reads as not valid."""
    return _probe_cookie(domain, cookie_header, timeout) is True


def _is_directory_blocked(root: Path) -> bool:
    """True if `root` exists but this process can't read its contents.

    macOS's Full Disk Access restriction doesn't clear a directory's unix
    permission bits, so `os.access` alone can say "readable" while every real
    read raises `PermissionError`. Check both: `os.access` catches the
    ordinary case, the read attempt catches TCC's silent block.
    """
    if not root.exists():
        return False
    if not os.access(root, os.R_OK):
        return True
    try:
        with os.scandir(root) as entries:
            next(entries, None)
    except PermissionError:
        return True
    return False


def _detect_blocked_browsers(browser: str | None) -> list[str]:
    """Browser names whose cookie-data directory exists but can't be read.

    Covers the Chromium-family roots and the Firefox root — the two cases
    where macOS blocks a directory listing outright before browser_cookie3
    gets a chance to say anything useful. Safari doesn't scan a directory
    (its cookie store is a single file), so its own load error covers it.
    """
    selected = SUPPORTED_BROWSERS if browser is None else (browser,)
    blocked: list[str] = []
    for name in selected:
        if name in _CHROMIUM_PROFILE_ROOTS:
            roots = _CHROMIUM_PROFILE_ROOTS[name]
        elif name == "firefox":
            roots = [_FIREFOX_ROOT]
        else:
            continue
        if any(_is_directory_blocked(root) for root in roots):
            blocked.append(name)
    return blocked


def _all_readable_browsers_blocked(browser: str | None, blocked: list[str]) -> bool:
    """True when every installed, directory-checkable candidate is blocked.

    An uninstalled browser is neither blocked nor a reason to keep polling, so
    only an installed Chromium/Firefox root that isn't blocked counts as a
    reason a valid session could still show up. Safari isn't directory-checked
    at all, so a detected Safari default (or an explicit --browser safari)
    always counts as a live candidate — this check otherwise has no way to
    see it.
    """
    if browser == "safari" or (browser is None and _default_https_browser() == "safari"):
        return False
    selected = SUPPORTED_BROWSERS if browser is None else (browser,)
    for name in selected:
        if name in _CHROMIUM_PROFILE_ROOTS:
            roots = _CHROMIUM_PROFILE_ROOTS[name]
        elif name == "firefox":
            roots = [_FIREFOX_ROOT]
        else:
            continue
        if name not in blocked and any(root.exists() for root in roots):
            return False
    return True


def _full_disk_access_hint() -> str:
    """macOS-specific remediation text; empty string on every other platform."""
    if sys.platform != "darwin":
        return ""
    return (
        " On macOS: grant your terminal app Full Disk Access under System Settings > "
        "Privacy & Security > Full Disk Access, restart the terminal, then run this command again."
    )


def _blocked_browser_note(blocked: list[str]) -> str:
    """One-line, printed once, while polling continues because another browser worked."""
    return f"note: {', '.join(blocked)} cookie data can't be read; skipping." + _full_disk_access_hint()


def _blocked_browser_message(blocked: list[str]) -> str:
    """`ClickException` text for when no cookies at all were found and a browser is blocked.

    Waiting out the timeout wouldn't help here — the browser holding the
    session may never become readable without the Full Disk Access grant.
    """
    return (
        f"No cookies found, and {', '.join(blocked)} cookie data can't be read "
        "(the OS is blocking this terminal from it)." + _full_disk_access_hint()
    )


def _wait_for_valid_cookie(
    domain: str,
    browser: str | None,
    timeout: float,
    interval: float,
) -> str:
    """Poll the browser cookie store until a valid Metabase session appears.

    Returns the cookie header on success. Raises `click.ClickException` after
    `timeout` seconds without finding a valid session — or immediately if no
    cookie candidate at all can be read and every installed candidate browser
    is blocked, since waiting out the timeout would never help in that case.
    A still-readable candidate might just need more time to complete SSO, so
    that case keeps polling as before.
    """
    blocked = _detect_blocked_browsers(browser)
    hopeless = bool(blocked) and _all_readable_browsers_blocked(browser, blocked)
    deadline = time.monotonic() + timeout
    last_status = ""
    seen_warnings: set[str] = set()
    rejected_headers: set[str] = set()
    blocked_note_printed = False
    while True:
        header, any_candidate = _find_valid_candidate(domain, browser, seen_warnings, rejected_headers)
        if header is not None:
            return header

        if not any_candidate and hopeless:
            raise click.ClickException(_blocked_browser_message(blocked))
        if blocked and not blocked_note_printed:
            click.echo(_blocked_browser_note(blocked))
            blocked_note_printed = True

        status = (
            "Cookies present but session not yet valid; still waiting..."
            if any_candidate
            else "Waiting for cookies: no browser profile has the full set yet..."
        )
        if status != last_status:
            click.echo(status)
            last_status = status

        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"Timed out after {timeout:.0f}s waiting for SSO. "
                "Make sure you completed login in the browser, or rerun with --browser to "
                "target a specific browser.",
            )
        time.sleep(interval)


def _login_region(region: str, browser: str | None, no_open: bool, timeout: float) -> None:
    """Authenticate one region: fast-path if already logged in, else open browser and wait."""
    domain = REGIONS[region]

    header, _ = _find_valid_candidate(domain, browser)
    if header is not None:
        path = _write_cookie_file(region, header)
        click.echo(f"[{region}] already logged in; saved cookie to {path}")
        return

    if not no_open:
        click.echo(f"[{region}] opening https://{domain} in your default browser.")
        webbrowser.open(f"https://{domain}")
    click.echo(f"[{region}] complete SSO in the browser; capturing automatically when ready.")

    cookie_header = _wait_for_valid_cookie(domain, browser, timeout, LOGIN_POLL_INTERVAL_SECONDS)
    path = _write_cookie_file(region, cookie_header)
    click.echo(f"[{region}] saved cookie to {path}")


@click.command(name="metabase:login", help="Log in to Metabase via SSO and cache the session cookie")
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    required=True,
    help="Region to authenticate (one at a time, e.g. --region us, --region eu, --region dev)",
)
@click.option(
    "--browser",
    type=click.Choice(SUPPORTED_BROWSERS),
    default=None,
    help="Read cookies from this browser only (default: try the system default browser first, then scan the rest)",
)
@click.option("--no-open", is_flag=True, help="Skip opening the browser; just capture cookies")
@click.option(
    "--timeout",
    type=float,
    default=LOGIN_TIMEOUT_SECONDS,
    show_default=True,
    help="Seconds to wait for SSO to complete before giving up",
)
def metabase_login(region: str, browser: str | None, no_open: bool, timeout: float) -> None:
    """Open Metabase in the default browser; capture cookies as soon as SSO completes.

    Already-valid sessions are fast-pathed (no browser tab opens),
    so re-running is cheap. Run once per region (us, eu).
    """
    _login_region(region, browser, no_open, timeout)


@click.command(name="metabase:cookie", help="Print the cached Metabase cookie header")
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    required=True,
    help="Region whose cached cookie to print (us, eu, dev)",
)
@click.option("--check/--no-check", default=False, help="Validate the cookie before printing")
def metabase_cookie(region: str, check: bool) -> None:
    """Print the cached cookie header to stdout. Suitable for `METABASE_COOKIE=$(...)`."""
    cookie_header = _read_cookie_file(region)
    if cookie_header is None:
        raise click.ClickException(
            f"No cached cookie for region {region}. Run `hogli metabase:login --region {region}`.",
        )
    if check and not _check_cookie(REGIONS[region], cookie_header):
        raise click.ClickException(
            f"Cached cookie for {region} is no longer valid. Run `hogli metabase:login --region {region}` to refresh.",
        )
    # No trailing newline so $(hogli metabase:cookie) yields a clean header.
    click.echo(cookie_header, nl=False)


def _require_cookie_header(region: str) -> str:
    """Return the cached cookie header or raise with a clear re-login message."""
    cookie_header = _read_cookie_file(region)
    if cookie_header is None:
        raise click.ClickException(
            f"No cached cookie for region {region}. Run `hogli metabase:login --region {region}`.",
        )
    return cookie_header


def _metabase_get(region: str, path: str, timeout: float = 30.0) -> Any:
    """GET `path` on the region's Metabase, return parsed JSON.

    Callers never see the cookie — it's read, used, and discarded internally.
    """
    import requests

    domain = REGIONS[region]
    cookie_header = _require_cookie_header(region)
    response = requests.get(
        f"https://{domain}{path}",
        headers={"Cookie": cookie_header, "Accept": "application/json"},
        timeout=timeout,
        allow_redirects=False,
    )
    if response.status_code in (301, 302):
        raise click.ClickException(
            f"Session redirected to auth for region {region}. "
            f"Run `hogli metabase:login --region {region}` to refresh cookies.",
        )
    if response.status_code == 401:
        raise click.ClickException(
            f"Session rejected (401) for region {region}. "
            f"Run `hogli metabase:login --region {region}` to refresh cookies.",
        )
    response.raise_for_status()
    return response.json()


def _metabase_post_dataset(region: str, database_id: int, sql: str, timeout: float = 120.0) -> Any:
    """POST a native SQL query to /api/dataset; return parsed JSON (incl. error body)."""
    import requests

    domain = REGIONS[region]
    cookie_header = _require_cookie_header(region)
    payload = {
        "database": database_id,
        "type": "native",
        "native": {"query": sql, "template-tags": {}},
    }
    response = requests.post(
        f"https://{domain}/api/dataset",
        headers={
            "Cookie": cookie_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=payload,
        timeout=timeout,
        allow_redirects=False,
    )
    if response.status_code in (301, 302):
        raise click.ClickException(
            f"Session redirected to auth for region {region}. "
            f"Run `hogli metabase:login --region {region}` to refresh cookies.",
        )
    if response.status_code == 401:
        raise click.ClickException(
            f"Session rejected (401) for region {region}. "
            f"Run `hogli metabase:login --region {region}` to refresh cookies.",
        )
    if response.status_code == 404:
        raise click.ClickException(
            f"Database {database_id} not found in region {region}. "
            f"Run `hogli metabase:databases --region {region}` to see current IDs.",
        )
    # Metabase sometimes returns 202 / 200 with a {status: failed, error: ...} body.
    try:
        body = response.json()
    except ValueError as exc:
        raise click.ClickException(
            f"Metabase returned non-JSON response (HTTP {response.status_code}): {response.text[:200]}",
        ) from exc
    return body


def _render_rows_tsv(body: dict[str, Any]) -> str:
    """Render /api/dataset JSON to a header-prefixed TSV string."""
    data = body.get("data") or {}
    cols = [c["name"] for c in data.get("cols") or []]
    rows = data.get("rows") or []
    out = ["\t".join(cols)]
    for row in rows:
        out.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(out) + "\n"


@click.command(
    name="metabase:databases",
    help="List Metabase databases (id, name, engine) for a region",
)
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    required=True,
    help="Region to inspect (us, eu, dev)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    show_default=True,
)
def metabase_databases(region: str, output_format: str) -> None:
    """Print current databases from /api/database. IDs change when Metabase's metadata DB is rebuilt or connections are re-added, so always run this before passing --database-id to metabase:query."""
    body = _metabase_get(region, "/api/database")
    # Metabase wraps the list in {data: [...], total: N}; older versions return a bare list.
    entries = body["data"] if isinstance(body, dict) and "data" in body else body

    if output_format == "json":
        click.echo(json.dumps([{"id": e["id"], "name": e["name"], "engine": e["engine"]} for e in entries], indent=2))
        return

    header = f"{'ID':>4}  {'NAME':<40}  ENGINE"
    click.echo(header)
    click.echo("-" * len(header))
    for e in entries:
        click.echo(f"{e['id']:>4}  {e['name']:<40}  {e['engine']}")


@click.command(
    name="metabase:query",
    help="Run a SQL query against Metabase /api/dataset; results to stdout",
)
@click.option(
    "--region",
    type=click.Choice(sorted(REGIONS.keys())),
    required=True,
    help="Region to query (us, eu, dev)",
)
@click.option(
    "--database-id",
    type=int,
    required=True,
    help="Database ID (get from `hogli metabase:databases --region <region>`)",
)
@click.option(
    "--file",
    "sql_file",
    type=click.Path(exists=True, dir_okay=False, readable=True),
    default=None,
    help="Read SQL from this file (default: read from stdin)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["tsv", "json"]),
    default="tsv",
    show_default=True,
)
@click.option(
    "--save",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write output to this file instead of stdout (avoids dumping large results into terminals/logs)",
)
@click.option(
    "--timeout",
    type=float,
    default=120.0,
    show_default=True,
    help="HTTP timeout in seconds",
)
def metabase_query(
    region: str,
    database_id: int,
    sql_file: str | None,
    output_format: str,
    save: str | None,
    timeout: float,
) -> None:
    """Run SQL against the given database ID and emit results. Cookie stays internal."""
    if sql_file:
        sql = Path(sql_file).read_text()
    else:
        sql = sys.stdin.read()
    if not sql.strip():
        raise click.ClickException("No SQL provided. Pipe via stdin or use --file.")

    body = _metabase_post_dataset(region, database_id, sql, timeout=timeout)
    if body.get("status") == "failed" or body.get("error"):
        error_msg = body.get("error") or body.get("status")
        raise click.ClickException(f"Query failed: {error_msg}")

    if output_format == "json":
        rendered = json.dumps(body, indent=2) + "\n"
    else:
        rendered = _render_rows_tsv(body)

    if save:
        _secure_write(Path(save), rendered)
        row_count = body.get("row_count", "?")
        click.echo(f"Wrote {row_count} rows to {save}")
    else:
        click.echo(rendered, nl=False)
