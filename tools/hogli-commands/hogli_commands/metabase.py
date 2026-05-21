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
import webbrowser
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
}

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
SUPPORTED_BROWSERS: tuple[str, ...] = ("chrome", "chromium", "brave", "firefox", "safari")
CACHE_DIR: Path = Path.home() / ".config" / "posthog" / "metabase"


def _cookie_path(region: str) -> Path:
    return CACHE_DIR / f"cookie-{region}"


def _format_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def _enumerate_cookie_files(browser: str | None) -> list[tuple[str, Path]]:
    """Return (loader_name, cookie_file_path) pairs for every browser profile to try.

    Chromium-family browsers (Chrome, Brave, Chromium) keep a `Cookies`
    SQLite db per profile (`Default`, `Profile 1`, ...). We glob each profile
    directory so users with multiple profiles (work + personal) don't have to
    care which one they logged in with.

    Firefox and Safari fall back to the default `browser_cookie3` loader.
    """
    targets: list[tuple[str, Path]] = []
    selected = SUPPORTED_BROWSERS if browser is None else (browser,)
    for name in selected:
        if name in _CHROMIUM_PROFILE_ROOTS:
            for root in _CHROMIUM_PROFILE_ROOTS[name]:
                if not root.exists():
                    continue
                for cookies_db in sorted(root.glob("*/Cookies")):
                    targets.append((name, cookies_db))
        else:
            targets.append((name, Path()))
    return targets


def _load_cookies_from_browser(domain: str, browser: str | None) -> dict[str, str]:
    """Read cookies for `domain` from the user's system browser cookie store.

    Decrypting Chromium cookies on macOS triggers a one-time Keychain prompt
    per profile; users who pick "Always allow" won't see it again.
    """
    try:
        import browser_cookie3
    except ImportError as exc:
        raise click.ClickException(
            "browser-cookie3 is not installed. Run `uv sync` to install dev dependencies.",
        ) from exc

    if browser is not None and browser not in SUPPORTED_BROWSERS:
        raise click.ClickException(f"Unsupported browser: {browser}")

    targets = _enumerate_cookie_files(browser)
    found: dict[str, str] = {}
    errors: list[str] = []
    for loader_name, cookie_file in targets:
        loader = getattr(browser_cookie3, loader_name, None)
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
        for cookie in jar:
            if cookie.name in REQUIRED_COOKIES and cookie.value:
                found[cookie.name] = cookie.value

    if not found and errors:
        click.echo("\n".join(f"  warn: {e}" for e in errors), err=True)
    return found


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


def _check_cookie(domain: str, cookie_header: str, timeout: float = 5.0) -> bool:
    """Hit /api/user/current to confirm the cookie is still valid."""
    import requests

    try:
        response = requests.get(
            f"https://{domain}/api/user/current",
            headers={"Cookie": cookie_header},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException:
        return False
    return response.status_code == 200


def _wait_for_valid_cookie(
    domain: str,
    browser: str | None,
    timeout: float,
    interval: float,
) -> str:
    """Poll the browser cookie store until a valid Metabase session appears.

    Returns the cookie header on success. Raises `click.ClickException` after
    `timeout` seconds without finding a valid session.
    """
    deadline = time.monotonic() + timeout
    last_status = ""
    last_header: str | None = None
    while True:
        cookies = _load_cookies_from_browser(domain, browser)
        missing = [name for name in REQUIRED_COOKIES if name not in cookies]
        if not missing:
            cookie_header = _format_cookie_header(cookies)
            # Avoid pinging /api/user/current with the same header repeatedly
            # when the user already had a stale cookie set on disk.
            if cookie_header != last_header:
                last_header = cookie_header
                if _check_cookie(domain, cookie_header):
                    return cookie_header
            status = "Cookies present but session not yet valid; still waiting..."
        else:
            status = f"Waiting for cookies: missing {missing}..."

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

    cookies = _load_cookies_from_browser(domain, browser)
    if all(name in cookies for name in REQUIRED_COOKIES):
        header = _format_cookie_header(cookies)
        if _check_cookie(domain, header):
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
    help="Read cookies from this browser only (default: scan all supported browsers)",
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
