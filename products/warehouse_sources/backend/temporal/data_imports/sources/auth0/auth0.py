import re
import json
import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.auth0.settings import (
    AUTH0_ENDPOINTS,
    MAX_PAGE_SIZE,
    SEARCH_RESULT_CAP,
    Auth0EndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 60

# The tenant domain is customer-supplied, so a hostile or misconfigured server could stream an
# arbitrarily large body. `requests` buffers a non-streamed response whole into a shared worker's
# memory before `.json()` runs, so every response is read with `stream=True` and capped here. A
# 100-row page of Auth0 users with large `app_metadata` is a few MiB, so this leaves headroom.
MAX_RESPONSE_BYTES = 100 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024
_ERROR_BODY_PREVIEW_BYTES = 2 * 1024
# `requests`' timeout only bounds each individual socket read, so a host that dribbles a body
# under that timeout could hold a worker open indefinitely. This bounds the whole transfer.
MAX_DOWNLOAD_SECONDS = 300

# A server that keeps returning full pages while omitting or inflating `total` would otherwise
# pin the (up to week-long) resumable activity in an endless fetch loop. At 100 rows per page
# this is far more than any real tenant holds.
MAX_PAGES = 100_000

# Access tokens are minted per run and are valid for 24h by default; re-mint this many seconds
# before the deadline so no request rides a token that expires mid-flight.
TOKEN_REFRESH_MARGIN_SECONDS = 60
DEFAULT_TOKEN_LIFETIME_SECONDS = 24 * 60 * 60

HOST_NOT_ALLOWED_ERROR = "Auth0 domain is not allowed"
PAGINATION_STALLED_ERROR = "Auth0 pagination could not advance past the 1000-result window"


class Auth0HostNotAllowedError(Exception):
    pass


class Auth0RetryableError(Exception):
    pass


class Auth0ResponseTooLargeError(Exception):
    pass


class Auth0ResponseTooSlowError(Exception):
    pass


class Auth0PaginationLimitError(Exception):
    pass


class Auth0PaginationStalledError(Exception):
    pass


@dataclasses.dataclass
class Auth0ResumeConfig:
    # Zero-based page index within the current window. Query params are rebuilt
    # deterministically from the schema inputs, so page + window start is all we need.
    page: int
    # Lower bound of the Lucene date window currently being paged, or None while the run is
    # still inside the first (unfiltered) window.
    window_start: Optional[str] = None


def normalize_domain(domain: str) -> str:
    """Turn whatever the user typed into a bare Auth0 tenant domain.

    Accepts ``tenant.us.auth0.com``, ``https://tenant.us.auth0.com/`` or
    ``tenant.us.auth0.com/api/v2`` and returns ``tenant.us.auth0.com``.
    """
    domain = domain.strip()
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE)
    domain = domain.split("/")[0]
    return domain.strip().rstrip("/")


def _base_url(domain: str) -> str:
    return f"https://{normalize_domain(domain)}"


def management_audience(domain: str, api_version: str) -> str:
    """The Management API's audience identifier — always the canonical tenant domain."""
    return f"{_base_url(domain)}/api/{api_version}/"


def _read_capped_json(response: requests.Response) -> Any:
    """Parse a streamed JSON response, refusing a body past the size or time budget.

    The domain is customer-supplied, so a body must never be buffered unbounded, nor be allowed
    to hold the connection open by dribbling under the per-read timeout. ``iter_content`` decodes
    any content-encoding, so the size cap bounds the decompressed body. Both caps are permanent —
    re-fetching the same page yields the same body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise Auth0ResponseTooSlowError(
                    f"Auth0 response exceeded the {MAX_DOWNLOAD_SECONDS}s download budget; aborting"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise Auth0ResponseTooLargeError(
                    f"Auth0 response exceeded the {MAX_RESPONSE_BYTES}-byte limit; refusing to buffer it"
                )
            chunks.append(chunk)
    finally:
        response.close()
    return json.loads(b"".join(chunks))


def _read_body_preview(response: requests.Response) -> str:
    """Read a bounded prefix of a streamed body for error logging, never buffering it whole."""
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
        if time.monotonic() > deadline:
            break
        if not chunk:
            continue
        chunks.append(chunk)
        total += len(chunk)
        if total >= _ERROR_BODY_PREVIEW_BYTES:
            break
    return b"".join(chunks)[:_ERROR_BODY_PREVIEW_BYTES].decode("utf-8", errors="replace")


class Auth0TokenManager:
    """Mints and caches the Management API access token, re-minting before it expires.

    Auth0 has no interactive step for this: the customer registers a machine-to-machine
    application in their own tenant and we exchange its client credentials for a token scoped to
    the Management API audience.
    """

    def __init__(
        self, session: requests.Session, domain: str, client_id: str, client_secret: str, api_version: str
    ) -> None:
        self._session = session
        self._domain = normalize_domain(domain)
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_version = api_version
        self._token: Optional[str] = None
        self._deadline: float = 0.0

    def get_token(self) -> str:
        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._mint()
        assert self._token is not None
        return self._token

    def _mint(self) -> None:
        response = self._session.post(
            f"{_base_url(self._domain)}/oauth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "audience": management_audience(self._domain, self._api_version),
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
            stream=True,
        )

        try:
            if response.status_code == 429 or response.status_code >= 500:
                raise Auth0RetryableError(f"Auth0 token request failed (retryable): status={response.status_code}")

            # A 3xx is not an error status, so reject it explicitly rather than following it to a
            # potentially internal Location (SSRF).
            if response.is_redirect or response.is_permanent_redirect:
                raise Auth0HostNotAllowedError(
                    f"Auth0 returned an unexpected redirect (status={response.status_code}); refusing to follow it"
                )

            response.raise_for_status()
            payload = _read_capped_json(response)
        finally:
            response.close()

        self._token = payload["access_token"]
        self._deadline = time.monotonic() + float(payload.get("expires_in") or DEFAULT_TOKEN_LIFETIME_SECONDS)


def _format_window_value(value: Any) -> str:
    """Render an incremental watermark as the ISO-8601 instant Auth0's query syntax expects."""
    if isinstance(value, datetime):
        instant = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return _format_window_value(datetime.combine(value, datetime.min.time(), tzinfo=UTC))
    # Double quotes would terminate the quoted Lucene term and let the rest of the value be read
    # as query syntax, so they never reach the query string.
    return str(value).replace('"', "")


def resolve_window_field(
    config: Auth0EndpointConfig, should_use_incremental_field: bool, incremental_field: Optional[str]
) -> Optional[str]:
    """The field the collection is sorted by and the Lucene window slides on.

    On an incremental run this is the cursor the user picked in the schema settings; on a full
    refresh it falls back to the endpoint's immutable timestamp so page boundaries stay stable.
    """
    if config.window_field is None:
        return None
    if not should_use_incremental_field:
        return config.full_refresh_window_field or config.window_field
    advertised = {f["field"] for f in config.incremental_fields}
    if incremental_field in advertised:
        return incremental_field
    return config.window_field


def _build_params(
    config: Auth0EndpointConfig,
    page: int,
    window_field: Optional[str],
    window_start: Optional[str],
) -> dict[str, Any]:
    if not config.paginated:
        return {}

    params: dict[str, Any] = {"page": page, "per_page": min(config.page_size, MAX_PAGE_SIZE)}
    if config.supports_include_totals:
        params["include_totals"] = "true"
    if config.search_engine:
        params["search_engine"] = config.search_engine
    if window_field:
        # `:1` is Auth0's ascending sort order. Rows must arrive oldest-first for the pipeline's
        # watermark to checkpoint per batch and for the window to slide forward.
        params["sort"] = f"{window_field}:1"
        if window_start is not None:
            # Inclusive lower bound: the boundary row is re-read and deduped by the merge on the
            # primary key, which is cheaper than risking a skipped row on an exclusive bound.
            params["q"] = f'{window_field}:["{window_start}" TO *]'
    return params


def _build_url(domain: str, config: Auth0EndpointConfig, api_version: str, params: dict[str, Any]) -> str:
    url = f"{_base_url(domain)}{config.path_template.format(version=api_version)}"
    if not params:
        return url
    return f"{url}?{urlencode(params, doseq=True)}"


def _extract_rows(data: Any, config: Auth0EndpointConfig) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and config.data_key:
        rows = data.get(config.data_key)
        return rows if isinstance(rows, list) else []
    return []


def _max_window_value(rows: list[dict[str, Any]], window_field: str) -> Optional[str]:
    """Newest window-field value on a page.

    Auth0 renders both `updated_at` and `date` as fixed-width ISO-8601 UTC instants, so string
    ordering matches chronological ordering. Rows arrive ascending, but the maximum is taken
    explicitly rather than trusting the last row.
    """
    values = [str(row[window_field]) for row in rows if isinstance(row, dict) and row.get(window_field)]
    return max(values) if values else None


def validate_credentials(
    domain: str,
    client_id: str,
    client_secret: str,
    api_version: str,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Mint a Management API token to confirm the machine-to-machine credentials are genuine.

    Auth0 grants scopes per collection, so an application may legitimately lack access to
    endpoints the user never intends to sync — at source-create (``schema_name is None``) a
    successful token exchange is enough. A scoped probe (``schema_name`` set) additionally
    requests the collection and treats a denial as a hard failure, naming the missing scope.
    """
    normalized = normalize_domain(domain)
    if not normalized or not re.match(r"^[A-Za-z0-9.\-]+$", normalized):
        return False, "Invalid Auth0 domain"

    # The domain is fully customer-controlled, so block one resolving to a private/internal
    # address (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(normalized, team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    # capture=False keeps the minted token (returned in the body) and any probed row content out
    # of opt-in HTTP sample capture — the name-based scrubbers cannot recognise either.
    session = make_tracked_session(capture=False, redact_values=(client_secret,))
    token_manager = Auth0TokenManager(session, normalized, client_id, client_secret, api_version)
    try:
        token = token_manager.get_token()
    except Auth0HostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            return False, "Invalid Auth0 client ID or client secret"
        return False, str(e)
    except (Auth0RetryableError, requests.exceptions.RequestException) as e:
        return False, str(e)

    if schema_name is None:
        return True, None

    config = AUTH0_ENDPOINTS[schema_name]
    probe_params = {"page": 0, "per_page": 1} if config.paginated else {}
    try:
        # Stream and close without touching the body — the probe only needs the status, and a
        # customer-controlled server must not get to buffer an unbounded body at source-create.
        response = session.get(
            _build_url(normalized, config, api_version, probe_params),
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=10,
            allow_redirects=False,
            stream=True,
        )
        try:
            is_redirect = response.is_redirect or response.is_permanent_redirect
            status_code = response.status_code
        finally:
            response.close()
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if is_redirect:
        return False, HOST_NOT_ALLOWED_ERROR

    if status_code == 200:
        return True, None

    if status_code in (401, 403):
        return False, f"Your Auth0 application is missing the `{config.required_scope}` scope for {schema_name}"

    return False, f"Auth0 returned status {status_code} for {schema_name}"


def get_rows(
    domain: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Auth0ResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = AUTH0_ENDPOINTS[endpoint]

    # Re-check at run time (not just at source-create) in case the domain was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(normalize_domain(domain), team_id)
    if not host_ok:
        raise Auth0HostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    # The token exchange returns the credential in its body, which the name-based sample
    # scrubbers cannot recognise, so it never enters sample capture. The data session is reused
    # across pages so urllib3 keeps the connection alive.
    token_manager = Auth0TokenManager(
        make_tracked_session(capture=False, redact_values=(client_secret,)),
        domain,
        client_id,
        client_secret,
        api_version,
    )
    session = make_tracked_session(capture=config.capture_samples, redact_values=(client_secret,))

    def fetch(url: str) -> Any:
        # The tracked session already retries 429 and transient 5xx honoring Retry-After, which
        # is what Auth0's rate limiter returns — no second retry layer here.
        headers = {"Authorization": f"Bearer {token_manager.get_token()}", "Accept": "application/json"}
        response = session.get(
            url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS, allow_redirects=False, stream=True
        )
        try:
            if response.is_redirect or response.is_permanent_redirect:
                raise Auth0HostNotAllowedError(
                    f"Auth0 returned an unexpected redirect (status={response.status_code}); refusing to follow it"
                )
            if not response.ok:
                logger.error(
                    f"Auth0 API error: status={response.status_code}, body={_read_body_preview(response)}, url={url}"
                )
                response.raise_for_status()
            return _read_capped_json(response)
        finally:
            response.close()

    if not config.paginated:
        rows = _extract_rows(fetch(_build_url(domain, config, api_version, {})), config)
        if rows:
            yield rows
        return

    window_field = resolve_window_field(config, should_use_incremental_field, incremental_field)
    window_start: Optional[str] = None
    if window_field and should_use_incremental_field and db_incremental_field_last_value:
        window_start = _format_window_value(db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = 0
    if resume_config is not None:
        page = resume_config.page
        window_start = resume_config.window_start
        logger.debug(f"Auth0: resuming {endpoint} from page {page} of window {window_start}")

    pages_fetched = 0
    while True:
        if pages_fetched >= MAX_PAGES:
            raise Auth0PaginationLimitError(
                f"Auth0 pagination for {endpoint} exceeded {MAX_PAGES} pages without terminating"
            )

        data = fetch(_build_url(domain, config, api_version, _build_params(config, page, window_field, window_start)))
        pages_fetched += 1

        rows = _extract_rows(data, config)
        if not rows:
            break

        yield rows

        next_page = page + 1
        total = data.get("total") if isinstance(data, dict) else None
        if isinstance(total, int) and next_page * config.page_size >= total:
            break
        if len(rows) < config.page_size:
            break

        next_window_start = window_start
        if window_field and next_page * config.page_size >= SEARCH_RESULT_CAP:
            # Auth0 refuses to page past the first 1000 matches, so restart at page 0 with the
            # window's lower bound moved up to the newest row seen.
            newest = _max_window_value(rows, window_field)
            if newest is None:
                raise Auth0PaginationStalledError(
                    f"{PAGINATION_STALLED_ERROR}: {endpoint} rows carry no `{window_field}` value to slide on"
                )
            if newest == window_start:
                raise Auth0PaginationStalledError(
                    f"{PAGINATION_STALLED_ERROR}: more than {SEARCH_RESULT_CAP} {endpoint} rows share "
                    f"`{window_field}` = {newest}"
                )
            next_window_start = newest
            next_page = 0

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — the
        # merge dedupes it on the primary key.
        resumable_source_manager.save_state(Auth0ResumeConfig(page=next_page, window_start=next_window_start))
        page = next_page
        window_start = next_window_start


def auth0_source(
    domain: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Auth0ResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = AUTH0_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            domain=domain,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            api_version=api_version,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        # Every windowed collection is requested with `sort=<field>:1`, so rows arrive oldest
        # first and the watermark advances correctly.
        sort_mode="asc",
    )
