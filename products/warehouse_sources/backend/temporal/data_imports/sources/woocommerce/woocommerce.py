import dataclasses
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

from requests import PreparedRequest, Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    TrackedHTTPAdapter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
)

# All WooCommerce REST API v3 endpoints hang off this path on the store domain.
WOOCOMMERCE_API_BASE_PATH = "/wp-json/wc/v3"
# WooCommerce caps `per_page` at 100.
DEFAULT_PER_PAGE = 100


@dataclasses.dataclass
class WooCommerceResumeConfig:
    page: int


def normalize_store_url(store_url: str) -> str:
    """Normalize a user-supplied store URL to an HTTPS base with no trailing slash.

    The WooCommerce REST API requires HTTPS for consumer key/secret Basic Auth, so
    an `http://` (or scheme-less) value is upgraded to `https://`. Any path segment
    the user includes (e.g. a store hosted under `/store`) is preserved.
    """
    url = store_url.strip().rstrip("/")
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    elif not url.startswith("https://"):
        url = "https://" + url
    return url


def _base_url(store_url: str) -> str:
    return f"{normalize_store_url(store_url)}{WOOCOMMERCE_API_BASE_PATH}"


def _assert_host_safe(store_url: str, team_id: int) -> None:
    """Block SSRF: reject store URLs that resolve to internal/private hosts.

    The store URL is fully user-controlled and drives server-side requests, so it
    must be vetted before any outbound call. `_is_host_safe` is a no-op on
    self-hosted instances and blocks private/internal IPs on PostHog Cloud.
    """
    host = urlparse(normalize_store_url(store_url)).hostname or ""
    is_safe, error = _is_host_safe(host, team_id)
    if not is_safe:
        raise ValueError(error or "WooCommerce store host is not allowed")


class _HostGuardedAdapter(TrackedHTTPAdapter):
    """Re-validate the destination host on every dispatched request, redirects included.

    The up-front `_assert_host_safe` check only vets the URL the user typed.
    `requests` invokes `send` once per hop, so an attacker who passes that check
    and then 30x-redirects the worker toward an internal address (the classic
    open-redirect SSRF bypass) is blocked here instead. Legitimate cross-host
    redirects to public hosts — e.g. apex→www canonicalization — still resolve.
    """

    def __init__(self, team_id: int, **kwargs: Any) -> None:
        self._team_id = team_id
        super().__init__(**kwargs)

    def send(
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | tuple[float, None] | None = None,
        verify: bool | str = True,
        cert: bytes | str | tuple[bytes | str, bytes | str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        host = urlparse(request.url or "").hostname or ""
        is_safe, error = _is_host_safe(host, self._team_id)
        if not is_safe:
            raise ValueError(error or "WooCommerce store host is not allowed")
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)


def _make_guarded_session(team_id: int, redact_values: tuple[str, ...] = ()) -> Session:
    """A tracked `requests.Session` that re-checks every hop's host against SSRF rules."""
    # nosemgrep: data-imports-http-transport-requests-session -- mounts a TrackedHTTPAdapter subclass below, so logging/metrics are preserved while adding per-hop host validation.
    session = Session()
    adapter = _HostGuardedAdapter(team_id, max_retries=DEFAULT_RETRY, redact_values=redact_values)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _to_woocommerce_datetime(value: Any) -> Optional[str]:
    """Format an incremental cursor value as the ISO8601 string WooCommerce expects.

    We pair this with `dates_are_gmt=true`, so timezone-aware values are normalized
    to UTC first. WooCommerce expects `YYYY-MM-DDTHH:MM:SS` with no offset.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


class WooCommercePaginator(BasePaginator):
    """Page-number pagination for the WooCommerce REST API.

    WooCommerce returns the total page count in the `X-WP-TotalPages` header and a
    JSON array as the body. We page until the header says we're done, falling back
    to stopping on a short/empty page when the header is absent. The current page
    number is the resumable checkpoint.
    """

    def __init__(self, per_page: int = DEFAULT_PER_PAGE, page: int = 1) -> None:
        super().__init__()
        self.per_page = per_page
        self.page = page

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page
        request.params["per_page"] = self.per_page

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        total_pages: Optional[int] = None
        header = response.headers.get("X-WP-TotalPages")
        if header is not None:
            try:
                total_pages = int(header)
            except ValueError:
                total_pages = None

        if total_pages is not None:
            self._has_next_page = self.page < total_pages
        else:
            # No header to lean on: stop once a page comes back shorter than a full batch.
            self._has_next_page = len(data) >= self.per_page

        if self._has_next_page:
            self.page += 1

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["page"] = self.page

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"page": self.page}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    path = ENDPOINT_PATHS[endpoint]
    use_incremental = should_use_incremental_field and endpoint in INCREMENTAL_FIELDS

    params: dict[str, Any] = {}
    if use_incremental:
        params["modified_after"] = {
            "type": "incremental",
            "cursor_path": "date_modified_gmt",
            "initial_value": None,
            "convert": _to_woocommerce_datetime,
        }
        params["dates_are_gmt"] = "true"

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": {
            # WooCommerce list endpoints return a top-level JSON array, so no
            # data_selector is needed.
            "path": path,
            "params": params,
        },
        "table_format": "delta",
    }


def woocommerce_source(
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WooCommerceResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    _assert_host_safe(store_url, team_id)

    config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(store_url),
            "auth": {
                "type": "http_basic",
                "username": consumer_key,
                "password": consumer_secret,
            },
            "paginator": WooCommercePaginator(),
            # Re-vet every hop (redirects included) so a redirect to an internal host can't
            # smuggle the credential past the up-front `_assert_host_safe` check.
            "session": _make_guarded_session(team_id, redact_values=(consumer_key, consumer_secret)),
        },
        # write_disposition is set per-resource by get_resource, so no defaults are needed.
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while there's a next page to resume to; the Redis TTL cleans up on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(WooCommerceResumeConfig(page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(store_url: str, consumer_key: str, consumer_secret: str, team_id: int) -> Optional[int]:
    """Probe a cheap authenticated endpoint. Returns the HTTP status code, or None on a connection error.

    Returns None (treated as a connection failure by the caller) for store URLs that resolve to an
    internal/private host, so a blocked SSRF target never reaches an outbound request.
    """
    host = urlparse(normalize_store_url(store_url)).hostname or ""
    is_safe, _ = _is_host_safe(host, team_id)
    if not is_safe:
        return None

    try:
        # The guarded session re-checks the host on any redirect hop, so a public store that
        # 30x-redirects to an internal address can't slip the probe past the up-front check.
        response = _make_guarded_session(team_id, redact_values=(consumer_key, consumer_secret)).get(
            f"{_base_url(store_url)}/products",
            params={"per_page": 1},
            auth=(consumer_key, consumer_secret),
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
