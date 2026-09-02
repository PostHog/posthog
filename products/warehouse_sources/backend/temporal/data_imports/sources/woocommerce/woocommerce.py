import secrets
import dataclasses
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import pyarrow as pa
from requests import PreparedRequest, Request, RequestException, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    TrackedHTTPAdapter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.woocommerce.settings import (
    ENDPOINT_PATHS,
    INCREMENTAL_FIELDS,
    WEBHOOK_TOPICS,
)

# All WooCommerce REST API v3 endpoints hang off this path on the store domain.
WOOCOMMERCE_API_BASE_PATH = "/wp-json/wc/v3"
# WooCommerce caps `per_page` at 100.
DEFAULT_PER_PAGE = 100
# Managed WordPress hosts and security layers (Cloudflare, Wordfence, and similar WAFs)
# frequently block the default `python-requests` User-Agent outright, returning a 403
# before the request ever reaches WooCommerce. Identify ourselves with a stable,
# non-default agent so those layers let legitimate sync traffic through.
WOOCOMMERCE_USER_AGENT = "PostHog Data Warehouse (WooCommerce source; +https://posthog.com)"
# Name given to every webhook we register, so a store owner can tell ours apart in
# WooCommerce > Settings > Advanced > Webhooks.
WEBHOOK_NAME = "PostHog Data warehouse"
# Webhook lists are page-numbered like every other WooCommerce collection. A store with more
# than this many webhooks is pathological; cap the scan rather than paging forever.
WEBHOOK_LIST_MAX_PAGES = 20
REQUEST_TIMEOUT_SECONDS = 30


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
    session.headers["User-Agent"] = WOOCOMMERCE_USER_AGENT
    return session


class WooCommerceAuth(AuthConfigBase):
    """WooCommerce consumer key/secret auth via query-string parameters.

    WooCommerce documents two ways to authenticate over HTTPS: an HTTP Basic
    `Authorization` header, or the consumer key/secret as query-string parameters. We
    use the query string and send no `Authorization` header at all, because the header
    is the more fragile path in practice. Some hosts strip the `Authorization` header
    before it reaches PHP, and some run a JWT/security plugin that greedily claims the
    header, expects a `Bearer` token, and rejects our `Basic` scheme with a 403
    (`jwt_auth_bad_auth_header`) before WooCommerce ever evaluates the key. The
    query string sidesteps both. The store URL is always normalized to HTTPS, so the
    credentials never travel over plaintext.
    """

    def __init__(self, consumer_key: str, consumer_secret: str) -> None:
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.prepare_url(
            request.url,
            {"consumer_key": self.consumer_key, "consumer_secret": self.consumer_secret},
        )
        return request

    def secret_values(self) -> tuple[str, ...]:
        # Both land in the request URL, so redact both from logs and raised exception messages.
        return tuple(value for value in (self.consumer_secret, self.consumer_key) if value)


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
            "auth": WooCommerceAuth(consumer_key, consumer_secret),
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


def webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Keep only the newest delivery per object id within one webhook batch.

    Deliveries land as the bare wc/v3 object, so the table is already shaped like the polled
    table. What it isn't is deduplicated: delta merge dedupes across syncs but not within a
    single source batch, so a `created` followed by an `updated` for the same order both survive
    into the batch and the merge would multi-match them. WooCommerce stamps every one of these
    objects with `date_modified_gmt`, which is ISO8601 and therefore lexicographically ordered;
    ties fall back to delivery order, which S3 preserves.
    """
    if table.num_rows == 0 or "id" not in table.column_names:
        return table

    modified_column = (
        table.column("date_modified_gmt").to_pylist()
        if "date_modified_gmt" in table.column_names
        else [None] * table.num_rows
    )

    latest_by_id: dict[Any, tuple[str, dict[str, Any]]] = {}
    for row, modified in zip(table.to_pylist(), modified_column):
        row_id = row.get("id")
        if row_id is None:
            continue
        modified_at = str(modified) if modified is not None else ""
        existing = latest_by_id.get(row_id)
        if existing is None or modified_at >= existing[0]:
            latest_by_id[row_id] = (modified_at, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


def _webhook_error(response: Response, action: str) -> str:
    """Turn a failed webhook-management response into something the user can act on."""
    if response.status_code in (401, 403):
        return (
            f"Your WooCommerce API key is not allowed to {action} webhooks. Webhook management needs a "
            "key with **Read/Write** permission - edit the key under WooCommerce > Settings > Advanced > "
            "REST API, or set the webhooks up manually."
        )

    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            detail = f": {body['message']}"
    except ValueError:
        pass

    return f"WooCommerce returned {response.status_code} when trying to {action} webhooks{detail}."


def _list_webhooks(
    store_url: str, consumer_key: str, consumer_secret: str, team_id: int
) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Every webhook registered on the store, paged. Returns (webhooks, error)."""
    session = _make_guarded_session(team_id, redact_values=(consumer_key, consumer_secret))
    auth = WooCommerceAuth(consumer_key, consumer_secret)
    url = f"{_base_url(store_url)}/webhooks"

    webhooks: list[dict[str, Any]] = []
    for page in range(1, WEBHOOK_LIST_MAX_PAGES + 1):
        # `status=all` is required: WooCommerce's default list hides paused and auto-disabled
        # webhooks, and those are exactly the ones we need to find and reactivate rather than
        # duplicate.
        params: dict[str, str | int] = {"per_page": DEFAULT_PER_PAGE, "page": page, "status": "all"}
        try:
            response = session.get(
                url,
                params=params,
                auth=auth,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (RequestException, ValueError) as e:
            return [], f"Could not reach your WooCommerce store to list webhooks: {e}"

        if not response.ok:
            return [], _webhook_error(response, "list")

        try:
            batch = response.json()
        except ValueError:
            return [], "Your WooCommerce store returned an unexpected response when listing webhooks."

        if not isinstance(batch, list) or not batch:
            break

        webhooks.extend(item for item in batch if isinstance(item, dict))

        if len(batch) < DEFAULT_PER_PAGE:
            break

    return webhooks, None


def _webhooks_for_url(webhooks: list[dict[str, Any]], webhook_url: str) -> list[dict[str, Any]]:
    return [webhook for webhook in webhooks if webhook.get("delivery_url") == webhook_url]


def create_webhook(
    store_url: str, consumer_key: str, consumer_secret: str, team_id: int, webhook_url: str
) -> WebhookCreationResult:
    """Register one WooCommerce webhook per topic, all pointing at `webhook_url` with one secret.

    WooCommerce subscribes a webhook to exactly one topic, so a store ends up with one webhook per
    resource/event pair. All of them share the secret we generate here, which WooCommerce never
    echoes back on read - hence returning it via `extra_inputs` for the hog function to verify with.

    Existing webhooks on the same delivery URL are updated in place rather than duplicated, so a
    retried setup re-pins the new secret and reactivates anything WooCommerce auto-disabled after
    five failed deliveries.
    """
    try:
        _assert_host_safe(store_url, team_id)
    except ValueError as e:
        return WebhookCreationResult(success=False, error=str(e))

    existing, error = _list_webhooks(store_url, consumer_key, consumer_secret, team_id)
    if error is not None:
        return WebhookCreationResult(success=False, error=error)

    # WooCommerce runs the secret through `wp_specialchars_decode` before hashing, so the alphabet
    # has to be free of HTML entities - `token_urlsafe` is.
    secret = secrets.token_urlsafe(32)
    session = _make_guarded_session(team_id, redact_values=(consumer_key, consumer_secret, secret))
    auth = WooCommerceAuth(consumer_key, consumer_secret)
    url = f"{_base_url(store_url)}/webhooks"

    by_topic = {webhook.get("topic"): webhook for webhook in _webhooks_for_url(existing, webhook_url)}

    for topic in WEBHOOK_TOPICS:
        match = by_topic.get(topic)
        payload: dict[str, Any] = {"name": WEBHOOK_NAME, "status": "active", "secret": secret}
        if match is None:
            payload |= {"topic": topic, "delivery_url": webhook_url}
            target = url
        else:
            # WooCommerce accepts POST as well as PUT for an update, so one verb covers both.
            target = f"{url}/{match['id']}"

        try:
            response = session.post(target, json=payload, auth=auth, timeout=REQUEST_TIMEOUT_SECONDS)
        except (RequestException, ValueError) as e:
            error = f"Could not reach your WooCommerce store to create webhooks: {e}"
        else:
            if response.ok:
                continue
            error = _webhook_error(response, "create")

        # Partial success is worse than none: the setup flow switches every webhook-capable table
        # to webhook sync on success, so a table whose topic never registered would stop being
        # polled and receive nothing. Roll back what we just created and report the failure.
        delete_webhook(store_url, consumer_key, consumer_secret, team_id, webhook_url)
        return WebhookCreationResult(success=False, error=error)

    return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})


def delete_webhook(
    store_url: str, consumer_key: str, consumer_secret: str, team_id: int, webhook_url: str
) -> WebhookDeletionResult:
    """Delete every webhook on the store that delivers to `webhook_url`."""
    try:
        _assert_host_safe(store_url, team_id)
    except ValueError as e:
        return WebhookDeletionResult(success=False, error=str(e))

    existing, error = _list_webhooks(store_url, consumer_key, consumer_secret, team_id)
    if error is not None:
        return WebhookDeletionResult(success=False, error=error)

    matches = _webhooks_for_url(existing, webhook_url)
    if not matches:
        return WebhookDeletionResult(success=True)

    session = _make_guarded_session(team_id, redact_values=(consumer_key, consumer_secret))
    auth = WooCommerceAuth(consumer_key, consumer_secret)

    for webhook in matches:
        try:
            response = session.delete(
                f"{_base_url(store_url)}/webhooks/{webhook['id']}",
                # Webhooks don't support trashing - WooCommerce 501s without this.
                params={"force": "true"},
                auth=auth,
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except (RequestException, ValueError) as e:
            return WebhookDeletionResult(success=False, error=f"Could not reach your WooCommerce store: {e}")

        if not response.ok:
            return WebhookDeletionResult(success=False, error=_webhook_error(response, "delete"))

    return WebhookDeletionResult(success=True)


def get_external_webhook_info(
    store_url: str, consumer_key: str, consumer_secret: str, team_id: int, webhook_url: str
) -> ExternalWebhookInfo:
    """Report the webhooks currently registered on the store for `webhook_url`."""
    try:
        _assert_host_safe(store_url, team_id)
    except ValueError as e:
        return ExternalWebhookInfo(exists=False, url=webhook_url, error=str(e))

    existing, error = _list_webhooks(store_url, consumer_key, consumer_secret, team_id)
    if error is not None:
        return ExternalWebhookInfo(exists=False, url=webhook_url, error=error)

    matches = _webhooks_for_url(existing, webhook_url)
    if not matches:
        return ExternalWebhookInfo(exists=False, url=webhook_url)

    statuses = [str(webhook.get("status")) for webhook in matches if webhook.get("status")]
    # WooCommerce disables a webhook after five consecutive delivery failures, and each topic has
    # its own webhook, so surface the unhealthy one rather than whichever came back first.
    unhealthy = sorted(status for status in statuses if status != "active")
    created = sorted(str(webhook["date_created_gmt"]) for webhook in matches if webhook.get("date_created_gmt"))

    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        enabled_events=sorted({str(webhook["topic"]) for webhook in matches if webhook.get("topic")}),
        status=unhealthy[0] if unhealthy else "active",
        created_at=created[0] if created else None,
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
            # Same query-string auth the sync uses, so the probe can't pass under one auth
            # path and then fail at sync time under another.
            auth=WooCommerceAuth(consumer_key, consumer_secret),
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
