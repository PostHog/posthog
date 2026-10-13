import re
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.crates_io.settings import (
    CRATES_IO_ENDPOINTS,
    CratesIOEndpointConfig,
)

CRATES_IO_BASE_URL = "https://crates.io/api/v1"

REQUEST_TIMEOUT_SECONDS = 30
MAX_RETRY_ATTEMPTS = 5

# crates.io's crawler policy requires a descriptive User-Agent identifying the app and a contact;
# requests without one are blocked.
USER_AGENT = "posthog-data-warehouse (https://posthog.com; hey@posthog.com)"

# The crawler policy also asks clients to self-throttle to roughly one request per second rather
# than parallel-hammer the API.
THROTTLE_SECONDS = 1.0

# Each configured crate costs one or two requests per enabled stream on every sync, so cap the
# config to bound worker time and outbound fan-out — a malformed/abusive config can't tie up the
# pipeline.
MAX_CRATES = 500

VERSIONS_PER_PAGE = 100

# crates.io rejects a larger page size on its paginated list endpoints with a 400.
LIST_PER_PAGE = 100

# Dependencies are only exposed per version, so a crate with a long release history would cost one
# request per version on every sync. Only the most recently published versions are walked. The walk
# sorts by publish date rather than semver, so a backport released onto an older line is included
# and a stale high version number does not hold a slot.
MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES = 25

# A widely used crate has tens of thousands of reverse dependencies, which at the crawler-policy
# request rate would let one crate consume the whole sync. Cap the walk instead.
MAX_REVERSE_DEPENDENCY_PAGES = 100

# Termination guard for the registry-wide lookup endpoints. The walk normally stops on the first
# short page, so this only trips if the API stops signalling the end of the list.
MAX_LIST_PAGES = 1000

# Rows for a single crate are yielded in bounded chunks so a crate with a huge version history
# never forces one oversized in-memory Arrow conversion downstream. The pipeline batches on top of
# this, so the exact value only caps the per-yield list size.
MAX_ROWS_PER_BATCH = 5000

# crates.io only breaks daily downloads down per version for a crate's most recent versions; the
# remainder arrives in aggregate (`meta.extra_downloads`) with no version attribution. Those rows
# carry this sentinel so the `[crate, date, version]` primary key stays non-null and mergeable.
# Real crates.io version ids start at 1, so 0 can never collide.
EXTRA_DOWNLOADS_VERSION_ID = 0


class CratesIORetryableError(Exception):
    pass


class _RequestThrottle:
    """Spaces requests out per the crates.io crawler policy (~1 request/second)."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval_seconds = interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self._interval_seconds:
                time.sleep(self._interval_seconds - elapsed)
        self._last_request_at = time.monotonic()


def _normalize_name(name: str) -> str:
    """Normalize a crate name so aliases collapse to one key.

    crates.io treats ``-`` and ``_`` as interchangeable and names as case-insensitive
    (``serde-json`` and ``serde_json`` resolve to the same crate), so we de-duplicate on this
    form. Otherwise two aliases both resolve to the same canonical crate and emit rows with a
    colliding primary key.
    """
    return re.sub(r"-", "_", name).lower()


def parse_crates(raw: str | None) -> list[str]:
    """Parse the user's free-text ``crates`` field into a list of crate names.

    Accepts one crate per line and/or comma-separated names. Raises ``ValueError`` with an
    actionable message on empty input so the user fixes the config rather than getting a silently
    empty sync. Names are de-duplicated (on their normalized form) while preserving order.
    """
    if not raw:
        raise ValueError("At least one crate name is required.")

    crates: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[\n,]", raw):
        name = token.strip()
        if not name:
            continue
        normalized = _normalize_name(name)
        if normalized not in seen:
            seen.add(normalized)
            crates.append(name)

        if len(crates) > MAX_CRATES:
            raise ValueError(f"Too many crates: at most {MAX_CRATES} are allowed per source.")

    if not crates:
        raise ValueError("At least one crate name is required.")

    return crates


def _crate_url(crate: str) -> str:
    # crates.io resolves name aliases itself; percent-encode the path segment so an odd character
    # can't break out of the path.
    return f"{CRATES_IO_BASE_URL}/crates/{quote(crate, safe='')}"


@retry(
    retry=retry_if_exception_type((CratesIORetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    throttle: _RequestThrottle,
    url: str,
    logger: FilteringBoundLogger,
) -> dict[str, Any] | None:
    """Fetch a single JSON document from the crates.io API.

    Returns ``None`` for a 404 (crate not found) so a typo'd or deleted crate is skipped rather
    than failing the whole sync. Transient 429/5xx raise a retryable error; other client errors
    raise ``requests.HTTPError``.
    """
    throttle.wait()
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 404:
        logger.warning(f"crates.io: resource not found, skipping: url={url}")
        return None

    if response.status_code == 429 or response.status_code >= 500:
        raise CratesIORetryableError(f"crates.io API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"crates.io API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _canonical_name(crate: str, detail: dict[str, Any]) -> str:
    """Prefer crates.io's canonical crate id over the user's spelling.

    crates.io resolves ``serde-json`` and ``Serde_JSON`` to the same crate, but sub-resource
    responses (downloads, owners) don't echo the crate name back. Stamping rows with the canonical
    id keeps primary keys stable regardless of how the user typed the crate, and keeps join keys
    aligned with the `crates` and `versions` streams.
    """
    crate_obj = detail.get("crate") or {}
    return crate_obj.get("id") or crate


def _resolve_canonical_name(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> str | None:
    detail = _fetch_json(session, throttle, _crate_url(crate), logger)
    if detail is None:
        return None
    return _canonical_name(crate, detail)


def _crate_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per crate: the `crate` block of the detail endpoint."""
    detail = _fetch_json(session, throttle, _crate_url(crate), logger)
    if detail is None:
        return
    crate_obj = detail.get("crate")
    if isinstance(crate_obj, dict):
        yield crate_obj


def _version_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per published version, paginated via the API's seek cursor.

    ``meta.next_page`` is a ready-made query string (e.g. ``?per_page=100&seek=...``) or ``null``
    on the last page.
    """
    base_url = f"{_crate_url(crate)}/versions"
    next_query: str | None = f"?per_page={VERSIONS_PER_PAGE}"
    while next_query:
        document = _fetch_json(session, throttle, f"{base_url}{next_query}", logger)
        if document is None:
            return
        for version in document.get("versions") or []:
            if isinstance(version, dict):
                yield version
        next_query = (document.get("meta") or {}).get("next_page")


def _download_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per (crate, date, version id) from the ~90-day daily download window.

    Rows are stamped with the canonical crate name — the downloads response doesn't carry it, and
    `meta.extra_downloads` rows (aggregate downloads of versions outside the per-version breakdown)
    have no version either, so they get the sentinel version id so daily totals stay complete.
    """
    canonical = _resolve_canonical_name(session, throttle, crate, logger)
    if canonical is None:
        return
    document = _fetch_json(session, throttle, f"{_crate_url(crate)}/downloads", logger)
    if document is None:
        return

    for entry in document.get("version_downloads") or []:
        # `date` completes the primary key; a row missing it can't upsert cleanly, so skip it.
        if not isinstance(entry, dict) or not entry.get("date"):
            continue
        row = dict(entry)
        row["crate"] = canonical
        yield row

    for entry in (document.get("meta") or {}).get("extra_downloads") or []:
        if not isinstance(entry, dict) or not entry.get("date"):
            continue
        row = dict(entry)
        row["crate"] = canonical
        row["version"] = EXTRA_DOWNLOADS_VERSION_ID
        yield row


def _owner_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per owner (user or team), stamped with the canonical crate name."""
    canonical = _resolve_canonical_name(session, throttle, crate, logger)
    if canonical is None:
        return
    document = _fetch_json(session, throttle, f"{_crate_url(crate)}/owners", logger)
    if document is None:
        return
    for owner in document.get("users") or []:
        if not isinstance(owner, dict):
            continue
        row = dict(owner)
        row["crate"] = canonical
        yield row


def _iter_list_pages(
    session: requests.Session,
    throttle: _RequestThrottle,
    url: str,
    collection: str,
    logger: FilteringBoundLogger,
    max_pages: int,
    params: dict[str, str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield each page document of a page-numbered crates.io list endpoint.

    ``collection`` is the response key holding the page's rows, which is what decides when the walk
    ends: crates.io keeps serving pages past the end of the list, returning an empty array rather
    than an error, and `meta.total` drops to 0 there, so a short page is the only reliable signal.
    """
    for page in range(1, max_pages + 1):
        query = urlencode({**(params or {}), "per_page": LIST_PER_PAGE, "page": page})
        document = _fetch_json(session, throttle, f"{url}?{query}", logger)
        if document is None:
            return
        yield document
        if len(document.get(collection) or []) < LIST_PER_PAGE:
            return

    logger.warning(f"crates.io: page cap reached, results may be truncated: url={url}, max_pages={max_pages}")


def _dependency_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per dependency declared by the crate's most recent versions.

    Rows are stamped with the parent crate and version number: the endpoint's own `crate_id` names
    the crate being depended on, not the crate that declares the dependency.
    """
    query = urlencode({"per_page": MAX_VERSIONS_PER_CRATE_FOR_DEPENDENCIES, "sort": "date"})
    document = _fetch_json(session, throttle, f"{_crate_url(crate)}/versions?{query}", logger)
    if document is None:
        return

    versions = [
        version for version in (document.get("versions") or []) if isinstance(version, dict) and version.get("num")
    ]
    total = (document.get("meta") or {}).get("total")
    if isinstance(total, int) and total > len(versions):
        logger.warning(
            f"crates.io: version cap reached for dependencies, older versions skipped: "
            f"crate={crate}, synced={len(versions)}, total={total}"
        )

    for version in versions:
        num = str(version["num"])
        dependencies = _fetch_json(session, throttle, f"{_crate_url(crate)}/{quote(num, safe='')}/dependencies", logger)
        if dependencies is None:
            continue
        for dependency in dependencies.get("dependencies") or []:
            if not isinstance(dependency, dict):
                continue
            row = dict(dependency)
            # The version record carries the canonical crate name, so no extra lookup is needed.
            row["crate"] = version.get("crate") or crate
            row["version_num"] = num
            yield row


def _reverse_dependency_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    crate: str,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per version of another crate that depends on this crate.

    Each page carries the dependency edges and, separately, the dependent versions they point at,
    so the dependent crate and version number are joined onto the edge here. Without that a row
    only identifies the dependent by a numeric version id.
    """
    url = f"{_crate_url(crate)}/reverse_dependencies"
    for document in _iter_list_pages(
        session, throttle, url, "dependencies", logger, max_pages=MAX_REVERSE_DEPENDENCY_PAGES
    ):
        versions_by_id = {
            version["id"]: version
            for version in (document.get("versions") or [])
            if isinstance(version, dict) and version.get("id") is not None
        }
        for dependency in document.get("dependencies") or []:
            if not isinstance(dependency, dict):
                continue
            row = dict(dependency)
            # On this endpoint `crate_id` is the crate being depended on, already in canonical form.
            row["crate"] = dependency.get("crate_id") or crate
            version = versions_by_id.get(dependency.get("version_id")) or {}
            row["dependent_crate"] = version.get("crate")
            row["dependent_version_num"] = version.get("num")
            yield row


def _category_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per crates.io category. Registry-wide, so it does not depend on the configured crates."""
    for document in _iter_list_pages(
        session,
        throttle,
        f"{CRATES_IO_BASE_URL}/categories",
        "categories",
        logger,
        max_pages=MAX_LIST_PAGES,
        # Alphabetical is the API default, but the walk is page-numbered, so an explicit stable
        # order stops rows shifting across page boundaries while the sync runs.
        params={"sort": "alpha"},
    ):
        for row in document.get("categories") or []:
            if isinstance(row, dict):
                yield row


def _keyword_rows(
    session: requests.Session,
    throttle: _RequestThrottle,
    logger: FilteringBoundLogger,
) -> Iterator[dict[str, Any]]:
    """One row per crates.io keyword. Registry-wide, so it does not depend on the configured crates."""
    for document in _iter_list_pages(
        session,
        throttle,
        f"{CRATES_IO_BASE_URL}/keywords",
        "keywords",
        logger,
        max_pages=MAX_LIST_PAGES,
        params={"sort": "alpha"},
    ):
        for row in document.get("keywords") or []:
            if isinstance(row, dict):
                yield row


_ROW_BUILDERS: dict[
    str, Callable[[requests.Session, _RequestThrottle, str, FilteringBoundLogger], Iterator[dict[str, Any]]]
] = {
    "crates": _crate_rows,
    "versions": _version_rows,
    "downloads": _download_rows,
    "owners": _owner_rows,
    "dependencies": _dependency_rows,
    "reverse_dependencies": _reverse_dependency_rows,
}

# Registry-wide lookup tables: one pass per sync rather than one pass per configured crate.
_GLOBAL_ROW_BUILDERS: dict[
    str, Callable[[requests.Session, _RequestThrottle, FilteringBoundLogger], Iterator[dict[str, Any]]]
] = {
    "categories": _category_rows,
    "keywords": _keyword_rows,
}


def validate_credentials(crates_raw: str | None) -> tuple[bool, str | None]:
    """Confirm the config is usable by probing the first configured crate.

    crates.io's read APIs are unauthenticated, so there is no key to check; instead we confirm at
    least one crate is configured and that it resolves (200). A 404 means the crate name is wrong.
    """
    try:
        crates = parse_crates(crates_raw)
    except ValueError as exc:
        return False, str(exc)

    crate = crates[0]
    try:
        response = make_tracked_session(headers={"User-Agent": USER_AGENT}).get(
            _crate_url(crate), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the crates.io API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 404:
        return False, f"Crate '{crate}' was not found on crates.io. Check the spelling and try again."

    return False, f"crates.io API returned an unexpected status code: {response.status_code}"


def _chunked(rows: Iterator[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Stream rows into bounded chunks.

    A crate with a very large version history, or a registry-wide lookup table, is never
    materialized as one oversized list, and each yield caps the downstream Arrow conversion. The
    pipeline batches on top of this.
    """
    chunk: list[dict[str, Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= MAX_ROWS_PER_BATCH:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def get_rows(
    endpoint: str,
    crates: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every request so urllib3 keeps the connection alive; the
    # User-Agent is mandatory under the crates.io crawler policy.
    session = make_tracked_session(headers={"User-Agent": USER_AGENT})
    throttle = _RequestThrottle(THROTTLE_SECONDS)

    build_global_rows = _GLOBAL_ROW_BUILDERS.get(endpoint)
    if build_global_rows is not None:
        yield from _chunked(build_global_rows(session, throttle, logger))
        return

    build_rows = _ROW_BUILDERS[endpoint]
    for crate in crates:
        yield from _chunked(build_rows(session, throttle, crate, logger))


def crates_io_source(
    endpoint: str,
    crates_raw: str | None,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config: CratesIOEndpointConfig = CRATES_IO_ENDPOINTS[endpoint]
    crates = parse_crates(crates_raw)

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(endpoint=endpoint, crates=crates, logger=logger),
        primary_keys=config.primary_keys,
        # No server-side ordering to rely on; rows are grouped per crate as fetched.
        sort_mode="asc",
        **partition_kwargs,
    )
