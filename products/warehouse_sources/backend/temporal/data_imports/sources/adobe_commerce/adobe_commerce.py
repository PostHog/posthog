import re
import json
import time
import threading
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Literal, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from urllib3.util.retry import Retry

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.adobe_commerce.settings import (
    ADOBE_COMMERCE_ENDPOINTS,
    VALIDATION_PROBE_ENDPOINTS,
    AdobeCommerceEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

REQUEST_TIMEOUT_SECONDS = 120
VALIDATE_TIMEOUT_SECONDS = 20

# The store URL is customer-supplied, so a misconfigured or hostile host could stream an
# arbitrarily large body into a shared worker. Every response is read with `stream=True` and
# capped: a 200-row `/V1/orders` page with full line items is a few MiB, so this leaves headroom.
MAX_RESPONSE_BYTES = 200 * 1024 * 1024
_RESPONSE_CHUNK_BYTES = 64 * 1024
_ERROR_BODY_PREVIEW_BYTES = 2 * 1024
# `requests`' timeout only bounds each socket read, so a host dribbling a body under that timeout
# could hold a worker open indefinitely while staying under the size cap. Bound total transfer time.
MAX_DOWNLOAD_SECONDS = 600

# A server that returns a non-empty page forever (or omits/inflates `total_count`) would otherwise
# pin the activity until its timeout. At 100-200 rows a page this is far beyond any real catalog.
MAX_PAGES = 100_000
# Bound the loop's wall clock too, so a store that stays under `MAX_PAGES` by dribbling pages can't
# hold an import worker for the activity's week-long timeout. Magento's searchCriteria collections
# always carry `total_count`, so a real store terminates well before either bound — only a
# pathological one hits them, and resuming would just hand it more worker time, so both are
# non-retryable (see `PAGINATION_LIMIT_ERROR` in `get_non_retryable_errors`).
MAX_PAGINATION_SECONDS = 24 * 60 * 60

# Magento's admin token TTL is configurable (`oauth/access_token_lifetime/admin`) and defaults to
# 4 hours; the response carries no expiry, so assume the default and re-mint well before it.
ADMIN_TOKEN_LIFETIME_SECONDS = 4 * 60 * 60
TOKEN_REFRESH_MARGIN_SECONDS = 5 * 60

# The admin token endpoint returns a bare JSON string (the token itself), so a well-behaved store
# answers in under a kilobyte. Validation mints the token inline on the API request thread, so cap
# the exchange far tighter than a data page and give it a short deadline — a hostile store pointed
# at by `store_url` must not be able to tie up a worker by dribbling a huge body during validation.
TOKEN_RESPONSE_MAX_BYTES = 1 * 1024 * 1024
TOKEN_DOWNLOAD_SECONDS = 30

# Credential validation runs inline on the API request thread, so it opts out of transport retries:
# the shared policy honours a server-supplied `Retry-After` and sleeps between attempts, none of it
# bounded by the request timeout, so a hostile store could otherwise stall a worker with a 429/503
# and a large `Retry-After`. A sync run still uses the default retrying session.
_NO_RETRY = Retry(total=0)

# Magento compares searchCriteria datetime filters against MySQL `DATETIME` columns stored in UTC.
MAGENTO_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

HOST_NOT_ALLOWED_ERROR = "Adobe Commerce store URL is not allowed"
INCOMPLETE_CREDENTIALS_ERROR = "Adobe Commerce credentials are incomplete"
HTTPS_REQUIRED_ERROR = "Adobe Commerce store URL must use HTTPS"
PAGINATION_LIMIT_ERROR = "Adobe Commerce pagination did not terminate"
# Reached only after the tracked session's own transport-level retries for 429/5xx are exhausted
# (see `_mint`), so this is self-recovering — matched by `AdobeCommerceSource.get_retryable_errors`
# to keep it out of error tracking. The status code is left out of the constant since it varies.
ADMIN_TOKEN_RETRYABLE_ERROR = "Adobe Commerce admin token request failed (retryable)"

# A store code is a Magento code: letters, digits and underscores, starting with a letter.
_STORE_CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*)://")
# A DNS name or bare IPv4. IPv6 literals aren't accepted: a merchant's storefront is reached by
# name, and rejecting them keeps the host string unambiguous for the SSRF check.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?$")


class AdobeCommerceRetryableError(Exception):
    pass


class AdobeCommerceHostNotAllowedError(Exception):
    pass


class AdobeCommerceConfigurationError(Exception):
    pass


class AdobeCommerceResponseTooLargeError(Exception):
    pass


class AdobeCommerceResponseTooSlowError(Exception):
    pass


class AdobeCommercePaginationLimitError(Exception):
    pass


@dataclasses.dataclass
class AdobeCommerceResumeConfig:
    # Next 1-indexed `searchCriteria[currentPage]` to fetch. The rest of the query string is
    # rebuilt deterministically from the schema inputs, so the page number is all we persist.
    current_page: int


@frozen
class AdobeCommerceCredentials:
    method: Literal["access_token", "admin"]
    access_token: str | None = dataclasses.field(default=None, repr=False)
    username: str | None = None
    password: str | None = dataclasses.field(default=None, repr=False)

    def secret_values(self) -> tuple[str, ...]:
        return tuple(v for v in (self.access_token, self.password) if v)


def normalize_store_url(store_url: str) -> str:
    """Reduce whatever the merchant typed to a `scheme://host[:port][/subpath]` base.

    Magento is frequently installed in a subdirectory, so the path is preserved — but a pasted
    `/rest/...` suffix is stripped so the base is never doubled up. Anything without a usable
    host is rejected before a URL carrying the credential is built.
    """
    cleaned = store_url.strip().rstrip("/")
    if not cleaned:
        raise ValueError("Enter your Adobe Commerce store URL, e.g. https://store.example.com")

    scheme_match = _SCHEME_RE.match(cleaned)
    if scheme_match:
        scheme = scheme_match.group(1).lower()
        # Every request carries the integration token or admin login, so refuse plaintext
        # transport before a credential-bearing URL is ever built.
        if scheme == "http":
            raise ValueError(HTTPS_REQUIRED_ERROR)
        if scheme != "https":
            raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")
    else:
        cleaned = f"https://{cleaned}"

    parsed = urlparse(cleaned)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")
    if not _HOSTNAME_RE.match(parsed.hostname):
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")
    try:
        # `urlparse` only validates the port lazily, so force it here rather than letting a
        # malformed one surface mid-sync.
        _ = parsed.port
    except ValueError as e:
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}") from e

    path = parsed.path.rstrip("/")
    # Tolerate a pasted API base (`.../rest`, `.../rest/default/V1`) — everything from `/rest`
    # onwards is rebuilt by `_base_url`.
    rest_index = path.lower().find("/rest")
    if rest_index != -1:
        path = path[:rest_index]
    if ".." in path:
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")

    return f"{parsed.scheme.lower()}://{parsed.netloc}{path}"


def store_host(store_url: str) -> str:
    hostname = urlparse(normalize_store_url(store_url)).hostname
    if not hostname:
        raise ValueError(f"Invalid Adobe Commerce store URL: {store_url!r}")
    return hostname


def normalize_store_code(store_code: str | None) -> str:
    """Validate the optional store code. Blank means the default store view (`/rest/V1/...`)."""
    cleaned = (store_code or "").strip().strip("/")
    if not cleaned:
        return ""
    if not _STORE_CODE_RE.match(cleaned):
        raise ValueError(f"Invalid Adobe Commerce store code: {store_code!r}")
    return cleaned


def _base_url(store_url: str, store_code: str | None) -> str:
    code = normalize_store_code(store_code)
    prefix = f"/rest/{code}/V1" if code else "/rest/V1"
    return f"{normalize_store_url(store_url)}{prefix}"


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params, doseq=True)}"


def _format_magento_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        as_utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return as_utc.strftime(MAGENTO_DATETIME_FORMAT)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime(MAGENTO_DATETIME_FORMAT)
    return str(value)


def build_search_criteria(
    config: AdobeCommerceEndpointConfig,
    page: int,
    cursor_field: str | None = None,
    cursor_value: Any = None,
) -> dict[str, Any]:
    """Build the flat `searchCriteria[...]` query params for one page.

    Magento takes its search criteria as bracketed PHP-array keys rather than nested JSON, so the
    filter group, sort order and paging all flatten into single-level keys here.
    """
    params: dict[str, Any] = {
        "searchCriteria[pageSize]": config.page_size,
        "searchCriteria[currentPage]": page,
    }

    if cursor_field:
        params["searchCriteria[sortOrders][0][field]"] = cursor_field
        params["searchCriteria[sortOrders][0][direction]"] = "ASC"
        if cursor_value is not None:
            # `gteq` re-reads the boundary row rather than risking a skip when several rows share
            # the same second; the merge dedupes it on the primary key.
            params["searchCriteria[filter_groups][0][filters][0][field]"] = cursor_field
            params["searchCriteria[filter_groups][0][filters][0][value]"] = _format_magento_datetime(cursor_value)
            params["searchCriteria[filter_groups][0][filters][0][condition_type]"] = "gteq"
    else:
        params["searchCriteria[sortOrders][0][field]"] = config.sort_field
        params["searchCriteria[sortOrders][0][direction]"] = "ASC"

    return params


def _read_capped_json(
    response: requests.Response,
    max_bytes: int | None = None,
    max_seconds: int | None = None,
) -> Any:
    """Parse a streamed JSON body, refusing one past the size or wall-clock budget.

    The host is customer-controlled, so a body must never be buffered unbounded, nor be allowed to
    hold the connection open by dribbling under the per-read timeout. Both caps are permanent
    failures — re-fetching the same page returns the same oversized/slow body. The token exchange
    passes tighter caps than a data page since its body is a single short string.
    """
    # Resolved at call time (not as defaults) so the module-level caps stay patchable in tests.
    max_bytes = MAX_RESPONSE_BYTES if max_bytes is None else max_bytes
    max_seconds = MAX_DOWNLOAD_SECONDS if max_seconds is None else max_seconds
    result: dict[str, Any] = {}

    def _drain() -> None:
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    result["error"] = AdobeCommerceResponseTooLargeError(
                        f"Adobe Commerce response exceeded the {max_bytes}-byte limit; refusing to buffer it"
                    )
                    return
                chunks.append(chunk)
            result["body"] = b"".join(chunks)
        except Exception as e:
            result["error"] = e

    # `iter_content` blocks until its chunk fills while the socket's per-read timeout resets on every
    # byte, so a host dripping bytes could stall past `max_seconds` without any inline check running.
    # Read on a daemon thread we stop waiting on at the deadline, so the worker is freed even when the
    # underlying socket read never returns; the abandoned thread ends once that read eventually errors.
    worker = threading.Thread(target=_drain, daemon=True)
    worker.start()
    worker.join(max_seconds)
    try:
        if worker.is_alive():
            raise AdobeCommerceResponseTooSlowError(
                f"Adobe Commerce response exceeded the {max_seconds}s download budget; aborting"
            )
        if "error" in result:
            raise result["error"]
        return json.loads(result["body"])
    finally:
        response.close()


def _read_body_preview(response: requests.Response) -> str:
    result: dict[str, bytes] = {}

    def _drain() -> None:
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=_RESPONSE_CHUNK_BYTES):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= _ERROR_BODY_PREVIEW_BYTES:
                    break
        except Exception:
            # A preview read failing shouldn't mask the real error being logged.
            pass
        result["body"] = b"".join(chunks)[:_ERROR_BODY_PREVIEW_BYTES]

    # Same drip hazard as `_read_capped_json`: bound the error-preview read on a daemon thread and
    # give up at the deadline so a slow host can't stall the worker on the error path.
    worker = threading.Thread(target=_drain, daemon=True)
    worker.start()
    worker.join(MAX_DOWNLOAD_SECONDS)
    return result.get("body", b"").decode("utf-8", errors="replace")


class AdobeCommerceTokenManager:
    """Resolves the bearer token for a run.

    Integration access tokens are long-lived and used verbatim. Admin tokens are minted from the
    merchant's admin username and password against `POST /V1/integration/admin/token` and expire
    after Magento's configured lifetime (4 hours by default), so they are re-minted in place.
    """

    def __init__(self, session: requests.Session, base_url: str, credentials: AdobeCommerceCredentials) -> None:
        self._session = session
        self._base_url = base_url
        self._credentials = credentials
        self._token: str | None = None
        self._deadline: float = 0.0

    def get_token(self) -> str:
        if self._credentials.method == "access_token":
            if not self._credentials.access_token:
                raise AdobeCommerceConfigurationError(f"{INCOMPLETE_CREDENTIALS_ERROR}: access token required")
            return self._credentials.access_token

        if self._token is None or time.monotonic() >= self._deadline - TOKEN_REFRESH_MARGIN_SECONDS:
            self._mint()
        assert self._token is not None
        return self._token

    def _mint(self) -> None:
        if not self._credentials.username or not self._credentials.password:
            raise AdobeCommerceConfigurationError(
                f"{INCOMPLETE_CREDENTIALS_ERROR}: admin username and password required"
            )

        response = self._session.post(
            f"{self._base_url}/integration/admin/token",
            json={"username": self._credentials.username, "password": self._credentials.password},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            # `requests` applies this per socket op, so it also bounds the connect and
            # response-header wait — a hostile store can't stall the exchange before the body cap
            # kicks in while validation runs inline on the API thread.
            timeout=TOKEN_DOWNLOAD_SECONDS,
            allow_redirects=False,
            stream=True,
        )

        try:
            if response.status_code == 429 or response.status_code >= 500:
                raise AdobeCommerceRetryableError(f"{ADMIN_TOKEN_RETRYABLE_ERROR}: status={response.status_code}")
            # A 3xx is not an error status, so refuse it explicitly rather than following it to a
            # potentially internal Location.
            if response.is_redirect or response.is_permanent_redirect:
                raise AdobeCommerceHostNotAllowedError(
                    f"Adobe Commerce returned an unexpected redirect (status={response.status_code}) for the token request"
                )
            response.raise_for_status()
            try:
                payload = _read_capped_json(
                    response, max_bytes=TOKEN_RESPONSE_MAX_BYTES, max_seconds=TOKEN_DOWNLOAD_SECONDS
                )
            except (AdobeCommerceResponseTooLargeError, AdobeCommerceResponseTooSlowError) as e:
                # A real token is a short string, so an oversized or dribbled body means the URL
                # isn't a Magento token endpoint — permanent, not worth retrying.
                raise AdobeCommerceConfigurationError(
                    "Adobe Commerce returned an oversized admin token response; check the store URL points at a Magento REST API"
                ) from e
        finally:
            response.close()

        # The endpoint returns the token as a bare JSON string.
        if not isinstance(payload, str) or not payload:
            raise AdobeCommerceConfigurationError(
                "Adobe Commerce returned an unexpected admin token response; check the store URL points at a Magento REST API"
            )

        self._token = payload
        self._deadline = time.monotonic() + ADMIN_TOKEN_LIFETIME_SECONDS


def _make_session(
    credentials: AdobeCommerceCredentials, capture: bool = True, retry: Retry | None = None
) -> requests.Session:
    # `allow_redirects=False` keeps traffic pointed at the host that was validated. Secrets are
    # redacted from logged URLs and captured samples by value, since the admin password rides a
    # JSON body the name-based scrubbers can't recognise on every install. `retry=None` keeps the
    # default retrying policy; validation passes `_NO_RETRY` so its sleeps can't stall a worker.
    return make_tracked_session(
        retry=retry,
        redact_values=credentials.secret_values(),
        allow_redirects=False,
        capture=capture,
    )


def _request_page(
    session: requests.Session,
    token_manager: AdobeCommerceTokenManager,
    url: str,
    logger: FilteringBoundLogger,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> Any:
    """GET one URL with a fresh bearer token and return the parsed body.

    Transport-level retries for 429/5xx already live in the tracked session, so nothing is retried
    here — an exhausted status surfaces as an `HTTPError` and the activity retries the whole job.
    """
    headers = {"Authorization": f"Bearer {token_manager.get_token()}", "Accept": "application/json"}
    response = session.get(url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)

    try:
        if response.is_redirect or response.is_permanent_redirect:
            raise AdobeCommerceHostNotAllowedError(
                f"Adobe Commerce returned an unexpected redirect (status={response.status_code}); refusing to follow it"
            )
        if not response.ok:
            body = _read_body_preview(response)
            logger.error(f"Adobe Commerce API error: status={response.status_code}, body={body}, url={url}")
            response.raise_for_status()
        return _read_capped_json(response)
    finally:
        response.close()


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    """Pull the row list out of either response shape Magento uses.

    searchCriteria collections answer `{"items": [...], "total_count": N}`; the reference endpoints
    (store views, websites, countries) answer with a bare array.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [row for row in items if isinstance(row, dict)]
    raise AdobeCommerceRetryableError(f"Adobe Commerce returned an unexpected payload: {type(payload).__name__}")


def _total_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        total = payload.get("total_count")
        if isinstance(total, int):
            return total
    return None


def get_rows(
    store_url: str,
    store_code: str | None,
    credentials: AdobeCommerceCredentials,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdobeCommerceResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field_name: Optional[str] = None,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ADOBE_COMMERCE_ENDPOINTS[endpoint]

    # Re-check at run time, not just at source-create, in case the URL was edited or now resolves
    # to an internal address. Only enforced on cloud — see `_is_host_safe`.
    host_ok, host_err = _is_host_safe(store_host(store_url), team_id)
    if not host_ok:
        raise AdobeCommerceHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    base_url = _base_url(store_url, store_code)
    session = _make_session(credentials)
    # Token exchanges carry the credential in the request and response body, so keep them out of
    # opt-in HTTP sample capture entirely.
    token_manager = AdobeCommerceTokenManager(_make_session(credentials, capture=False), base_url, credentials)

    if not config.uses_search_criteria:
        payload = _request_page(session, token_manager, f"{base_url}{config.path}", logger)
        rows = _extract_items(payload)
        if rows:
            yield rows
        return

    cursor_field = (incremental_field_name or config.incremental_field_name) if should_use_incremental_field else None
    cursor_value = db_incremental_field_last_value if should_use_incremental_field else None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.current_page if resume is not None else 1
    if resume is not None:
        logger.debug(f"Adobe Commerce: resuming {endpoint} from page {page}")

    loop_deadline = time.monotonic() + MAX_PAGINATION_SECONDS
    while True:
        if page > MAX_PAGES:
            raise AdobeCommercePaginationLimitError(f"{PAGINATION_LIMIT_ERROR}: {endpoint} exceeded {MAX_PAGES} pages")
        if time.monotonic() > loop_deadline:
            raise AdobeCommercePaginationLimitError(
                f"{PAGINATION_LIMIT_ERROR}: {endpoint} exceeded the {MAX_PAGINATION_SECONDS}s pagination budget"
            )

        params = build_search_criteria(config, page, cursor_field, cursor_value)
        payload = _request_page(session, token_manager, _build_url(base_url, config.path, params), logger)
        rows = _extract_items(payload)
        if not rows:
            break

        yield rows

        total = _total_count(payload)
        if total is not None and page * config.page_size >= total:
            break
        # A short page also means the collection is exhausted, which covers a server that omits
        # `total_count` entirely.
        if len(rows) < config.page_size:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; the
        # merge dedupes on the primary key.
        page += 1
        resumable_source_manager.save_state(AdobeCommerceResumeConfig(current_page=page))


def adobe_commerce_source(
    store_url: str,
    store_code: str | None,
    credentials: AdobeCommerceCredentials,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[AdobeCommerceResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field_name: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ADOBE_COMMERCE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            store_url=store_url,
            store_code=store_code,
            credentials=credentials,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field_name=incremental_field_name,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Incremental runs ask Magento for `sortOrders[0][direction]=ASC` on the cursor column, so
        # the watermark can checkpoint after every batch.
        sort_mode="asc",
    )


def _probe(
    session: requests.Session,
    token_manager: AdobeCommerceTokenManager,
    base_url: str,
    endpoint: str,
    timeout: float,
) -> tuple[int, str | None]:
    """Request one row from an endpoint. Returns `(status, error_message)`; status 0 on transport failure."""
    config = ADOBE_COMMERCE_ENDPOINTS[endpoint]
    params = build_search_criteria(config, page=1) if config.uses_search_criteria else {}
    if params:
        params["searchCriteria[pageSize]"] = 1
    url = _build_url(base_url, config.path, params)

    try:
        headers = {"Authorization": f"Bearer {token_manager.get_token()}", "Accept": "application/json"}
        response = session.get(url, headers=headers, timeout=timeout, allow_redirects=False, stream=True)
    except requests.exceptions.RequestException as e:
        return 0, str(e)

    try:
        if response.is_redirect or response.is_permanent_redirect:
            return 0, HOST_NOT_ALLOWED_ERROR
        return response.status_code, None
    finally:
        response.close()


def validate_credentials(
    store_url: str,
    store_code: str | None,
    credentials: AdobeCommerceCredentials,
    schema_name: Optional[str] = None,
    team_id: Optional[int] = None,
) -> tuple[bool, str | None]:
    """Confirm the store URL and credentials actually reach a Magento REST API.

    At source-create (`schema_name is None`) the probe walks a short list of common read
    endpoints and passes on the first 200 — Magento answers an unauthorized *resource* with the
    same 401 it uses for a bad token, so one endpoint the integration happens not to cover would
    otherwise look identical to invalid credentials. With `schema_name` set the probe targets that
    endpoint only, so the schema picker reports its real access.
    """
    try:
        base_url = _base_url(store_url, store_code)
    except ValueError as e:
        return False, str(e)

    if team_id is not None:
        host_ok, host_err = _is_host_safe(store_host(store_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    session = _make_session(credentials, capture=False, retry=_NO_RETRY)
    token_manager = AdobeCommerceTokenManager(session, base_url, credentials)

    try:
        token_manager.get_token()
    except AdobeCommerceConfigurationError as e:
        return False, str(e)
    except AdobeCommerceHostNotAllowedError:
        return False, HOST_NOT_ALLOWED_ERROR
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status == 401:
            return False, "Adobe Commerce rejected the admin username and password."
        if status == 404:
            return False, "No Adobe Commerce REST API found at that store URL. Check the URL and store code."
        return False, f"Could not sign in to Adobe Commerce (HTTP {status})."
    except (AdobeCommerceRetryableError, requests.exceptions.RequestException) as e:
        return False, str(e)

    probes = (schema_name,) if schema_name is not None else VALIDATION_PROBE_ENDPOINTS
    last_status: int | None = None
    last_error: str | None = None
    # Bound the whole probe sequence to a single wall-clock budget so a host that stalls on every
    # endpoint can't tie up an API worker for `len(probes) * VALIDATE_TIMEOUT_SECONDS`.
    deadline = time.monotonic() + VALIDATE_TIMEOUT_SECONDS
    for endpoint in probes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            last_status, last_error = 0, "Adobe Commerce did not respond in time."
            break
        status, error = _probe(session, token_manager, base_url, endpoint, min(VALIDATE_TIMEOUT_SECONDS, remaining))
        if status == 200:
            return True, None
        last_status, last_error = status, error
        # A transport failure means the host is unreachable or stalling; the remaining endpoints live
        # on the same host, so stop rather than pay another timeout for each of them.
        if status == 0:
            break

    if last_status in (401, 403):
        return False, (
            "Adobe Commerce rejected the credentials. Check the token is valid and the integration has read "
            "access. On Magento 2.4.4 and later, also enable Stores → Configuration → Services → OAuth → "
            "Access Token Expiration → 'Allow OAuth Access Tokens to be used as standalone Bearer tokens'."
        )
    if last_status == 404:
        return False, "No Adobe Commerce REST API found at that store URL. Check the URL and store code."
    if last_status == 0:
        return False, last_error or "Could not connect to your Adobe Commerce store."
    return False, f"Adobe Commerce returned HTTP {last_status}."
