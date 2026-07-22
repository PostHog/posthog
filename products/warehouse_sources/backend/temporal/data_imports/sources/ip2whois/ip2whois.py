import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.ip2whois.settings import IP2WHOIS_ENDPOINTS

# Single WHOIS lookup endpoint. Auth is the API key on the `key` query param (the docs also allow a
# Bearer header — the query param is simpler and equivalent). One domain per request via `domain`.
IP2WHOIS_BASE_URL = "https://api.ip2whois.com/v2"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# Each domain costs one request on every sync, so cap the configured list to bound worker time and
# outbound fan-out. The free tier is capped at 500 lookups/month; paid plans raise the quota, so this
# is set above the free cap while still preventing a malformed/abusive config from tying up the worker.
MAX_DOMAINS = 1000

# A permissive registrable-domain shape: dot-separated labels of letters/digits/hyphens, ending in an
# alphabetic TLD. Deliberately lenient (accepts IDNs in punycode form, multi-level TLDs) — it only
# filters out obvious garbage (spaces, missing dot) so the sync doesn't burn a lookup credit on it.
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

# Error codes that are specific to the one domain being looked up (invalid/missing domain), so the
# sync skips just that entry and keeps going. This is an allow-list on purpose: only 10007 is
# curl-verified as domain-level, and the full code set for quota/disabled-key states could not be
# verified without a paid key. Any code NOT listed here — including unknown quota/account errors —
# fails the run loudly rather than silently swallowing every row, so a full-refresh sync can never
# replace the table with an empty result off the back of a misclassified account error.
_DOMAIN_LEVEL_ERROR_CODES: frozenset[int] = frozenset({10007})


class IP2WhoisRetryableError(Exception):
    pass


class IP2WhoisAPIError(Exception):
    pass


def normalize_domain(raw: str) -> str | None:
    """Normalize a single user-entered token into a bare registrable domain, or ``None`` if unusable.

    Accepts a raw hostname or a pasted URL. Strips any scheme, path/query, leading ``www.``, and
    surrounding punctuation, then lowercases. Returns ``None`` when the result doesn't look like a
    domain so the caller can skip it rather than spend an API lookup on garbage.
    """
    token = raw.strip()
    if not token:
        return None
    # Drop a scheme and everything after the host (path/query/fragment/port), if the user pasted a URL.
    token = re.sub(r"^[a-z][a-z0-9+.-]*://", "", token, flags=re.IGNORECASE)
    token = re.split(r"[/?#]", token, maxsplit=1)[0]
    token = token.split(":", 1)[0]
    token = token.strip().strip(".").lower()
    if token.startswith("www."):
        token = token[4:]
    if not token or not _DOMAIN_RE.match(token):
        return None
    return token


def parse_domains(raw: str | None) -> list[str]:
    """Parse the user's free-text ``domains`` field into a deduped list of registrable domains.

    Tokens may be separated by newlines, commas, or whitespace. Raises ``ValueError`` with an
    actionable message when nothing usable is found or the list is too long, so the user fixes the
    config instead of getting a silently empty sync.
    """
    if not raw or not raw.strip():
        raise ValueError("At least one domain is required.")

    seen: set[str] = set()
    domains: list[str] = []
    for token in re.split(r"[\s,]+", raw):
        domain = normalize_domain(token)
        if domain is None or domain in seen:
            continue
        seen.add(domain)
        domains.append(domain)
        if len(domains) > MAX_DOMAINS:
            raise ValueError(f"Too many domains: at most {MAX_DOMAINS} are allowed per source.")

    if not domains:
        raise ValueError("No valid domains found. Enter one domain per line, e.g. 'example.com'.")

    return domains


def _build_url(api_key: str, domain: str) -> str:
    # `format=json` is the API default, but we pass it explicitly so a change to the default can't
    # silently switch us to XML.
    return f"{IP2WHOIS_BASE_URL}?{urlencode({'key': api_key, 'domain': domain, 'format': 'json'})}"


def _safe_json(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@retry(
    retry=retry_if_exception_type((IP2WhoisRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_domain(
    session: requests.Session,
    api_key: str,
    domain: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any] | None:
    """Look up one domain. Returns the WHOIS row, or ``None`` when the failure is specific to this
    domain (so the rest of the list still syncs). Raises on retryable transport errors and on
    account-level failures (bad key, exhausted quota, or any unrecognized error) that should fail the
    whole sync.

    IP2WHOIS returns errors as ``{"error": {"error_code": N, "error_message": "..."}}`` — a bad key
    is HTTP 401 (code 10001) and an invalid/missing domain is HTTP 400 (code 10007). Only codes in
    ``_DOMAIN_LEVEL_ERROR_CODES`` skip a single entry; every other error fails the run loudly, so a
    misclassified account/quota error can never silently empty the (full-refresh) table.
    """
    response = session.get(_build_url(api_key, domain), timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and transient 5xx are retryable; back off and try again.
    if response.status_code == 429 or response.status_code >= 500:
        raise IP2WhoisRetryableError(f"IP2WHOIS API error (retryable): status={response.status_code}")

    body = _safe_json(response)
    error = body.get("error") if isinstance(body.get("error"), dict) else None

    # A rejected key (401/403) can never be satisfied by retrying, and every other domain would fail
    # the same way, so fail the whole sync. Build the message from the base URL only — the `key` query
    # param must never reach stored errors/logs. The host prefix is matched by get_non_retryable_errors.
    if response.status_code in (401, 403):
        reason = "Unauthorized" if response.status_code == 401 else "Forbidden"
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {reason} for url: {IP2WHOIS_BASE_URL}", response=response
        )

    if error is not None:
        code = error.get("error_code", "unknown")
        message = str(error.get("error_message", ""))
        # Only confirmed domain-level codes skip this one entry; anything else (key/quota/account, or
        # an unknown code) is fatal for the run — see _DOMAIN_LEVEL_ERROR_CODES.
        if code in _DOMAIN_LEVEL_ERROR_CODES:
            logger.warning(f"IP2WHOIS: skipping domain {domain}: [{code}] {message}")
            return None
        raise IP2WhoisAPIError(f"IP2WHOIS API error [{code}]: {message}")

    if not response.ok:
        # A non-2xx with no recognized error envelope can't be attributed to this specific domain, so
        # fail the run rather than silently dropping rows.
        raise IP2WhoisAPIError(f"IP2WHOIS API error: unexpected status {response.status_code}")

    # Stamp the queried (normalized) domain as the primary key so it's stable regardless of how the
    # API echoes it back (casing, IDN form). Keep any `domain` the API returned under `domain` too —
    # they should match, but the queried value is the one the user controls and will join on.
    body["domain"] = domain
    return body


def get_rows(
    api_key: str,
    domains: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every domain so urllib3 keeps the connection alive. `redact_values`
    # masks the API key (a query param) from the tracked session's logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,))

    yielded = 0
    skipped = 0
    for domain in domains:
        row = _fetch_domain(session, api_key, domain, logger)
        if row is not None:
            yielded += 1
            yield [row]
        else:
            skipped += 1

    # Full-refresh replaces the table with whatever this run yields. If every configured domain was
    # skipped we'd silently wipe the table to empty, which hides a real problem (a bad domain list, or
    # an account error that slipped through as a domain-level skip). Fail loudly instead.
    if yielded == 0 and skipped > 0:
        raise IP2WhoisAPIError(
            f"IP2WHOIS returned no WHOIS data for any of the {skipped} configured domain(s). Every domain "
            "was rejected — check the domain list and that the account's monthly lookup quota is not exhausted."
        )


def ip2whois_source(
    api_key: str,
    endpoint: str,
    domains_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = IP2WHOIS_ENDPOINTS[endpoint]
    domains = parse_domains(domains_raw)

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, domains=domains, logger=logger),
        primary_keys=config.primary_keys,
        # WHOIS is a current-state lookup with no server-side change cursor, so each sync fully
        # replaces the table. Rows carry a `create_date`, but it's absent/unparseable for some TLDs, so
        # it's not a safe partition key; the volume (one row per configured domain) is small enough
        # that partitioning would add cost without benefit.
        sort_mode="asc",
    )


def validate_credentials(api_key: str, domains_raw: str | None) -> tuple[bool, str | None]:
    """Probe the lookup endpoint with the first configured domain.

    IP2WHOIS validates the domain param's presence before the key, so a real domain is required to
    reach the key check. A valid key returns 200 (WHOIS data) or 400 (the probe domain was rejected,
    but the key was accepted); an invalid/disabled key returns 401/403 (code 10001).
    """
    try:
        domains = parse_domains(domains_raw)
    except ValueError as exc:
        return False, str(exc)

    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(_build_url(api_key, domains[0]), timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False, "Could not reach the IP2WHOIS API. Please try again."

    if response.status_code in (401, 403):
        return False, (
            "Your IP2WHOIS API key is invalid or has been disabled. Generate a new key in your "
            "IP2WHOIS dashboard, then reconnect."
        )

    body = _safe_json(response)
    error = body.get("error") if isinstance(body.get("error"), dict) else None
    if error is not None and "key" in str(error.get("error_message", "")).lower():
        return False, (
            "Your IP2WHOIS API key is invalid or has been disabled. Generate a new key in your "
            "IP2WHOIS dashboard, then reconnect."
        )

    # 200 (WHOIS data) or 400 (key accepted, probe domain rejected) both prove the key is genuine.
    if response.status_code in (200, 400):
        return True, None

    return False, f"The IP2WHOIS API returned an unexpected status code: {response.status_code}"
