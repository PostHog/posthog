import dataclasses
from datetime import datetime
from typing import Any, Optional

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync
from dateutil import parser
from requests import Request, Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fourthwall.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    FOURTHWALL_ENDPOINTS,
    PAGE_SIZE,
    WEBHOOK_EVENT_DATA_UNWRAP_KEY,
    WEBHOOK_SCHEMA_NAMES,
)

REQUEST_TIMEOUT_SECONDS = 30

# Lower bound used on the first incremental sync, before a watermark exists.
INCREMENTAL_INITIAL_VALUE = "1970-01-01T00:00:00Z"


@dataclasses.dataclass
class FourthwallResumeConfig:
    # Opaque framework paginator checkpoint (the next page number), round-tripped into
    # `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


def api_root(api_version: str) -> str:
    return f"{BASE_URL}/open-api/{api_version}"


def _format_datetime(value: Any) -> str:
    """Format the incremental watermark for Fourthwall's `updatedAt[gt]` filter.

    Truncates to whole seconds, which rounds the lower bound *down* — a sync re-reads at most a
    few boundary orders (the merge dedupes them) rather than skipping any order whose updatedAt
    equals the watermark.
    """
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _client_config(username: str, password: str, api_version: str) -> ClientConfig:
    return {
        "base_url": api_root(api_version),
        "auth": {"type": "http_basic", "username": username, "password": password},
        "headers": {"Accept": "application/json"},
        # Order, donation and member rows carry supporter names, emails and postal addresses,
        # so keep the raw bodies out of HTTP sample capture (still metered and logged).
        "session": make_tracked_session(capture=False, redact_values=(password,)),
        # The API user's credentials ride every request, so pin them to the Fourthwall origin
        # and refuse redirects rather than letting a 3xx move them somewhere else.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


class ProductTemplatePaginator(BasePaginator):
    """Page Fourthwall's product-templates list.

    That list carries a 1-based page number in the path (`/product-templates/page/{page}`) and
    returns only `{results, total}` — no `totalPages` and no page-size parameter. So advance the
    trailing path segment until a page comes back empty.
    """

    def __init__(self, page: int = 1) -> None:
        super().__init__()
        self.page = page
        self._page_base: Optional[str] = None

    def _apply_page(self, request: Request) -> None:
        if self._page_base is None:
            # The first URL ends in the page number; keep everything before it as the base.
            self._page_base = (request.url or "").rsplit("/", 1)[0]
        request.url = f"{self._page_base}/{self.page}"

    def init_request(self, request: Request) -> None:
        self._apply_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply_page(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"ProductTemplatePaginator(page={self.page})"


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    config = FOURTHWALL_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {"path": config.path}

    if config.page_in_path:
        # First page is 1; the paginator rewrites the trailing segment for later pages.
        endpoint_config["path"] = f"{config.path}/1"
        endpoint_config["data_selector"] = "results"
        endpoint_config["data_selector_required"] = True
        endpoint_config["paginator"] = ProductTemplatePaginator()
    elif config.paginated:
        endpoint_config["params"] = {"size": PAGE_SIZE}
        endpoint_config["data_selector"] = "results"
        # `results` is a required field of Fourthwall's page envelope, so a response without it
        # is a changed API shape — fail loud rather than quietly syncing zero rows.
        endpoint_config["data_selector_required"] = True
        # `totalPages` stops pagination on the last page instead of paying one extra empty
        # request; `base_page=0` matches Fourthwall's 0-based `page` parameter.
        endpoint_config["paginator"] = PageNumberPaginator(base_page=0, page_param="page", total_path="totalPages")
    else:
        endpoint_config["paginator"] = "single_page"

    if should_use_incremental_field and config.incremental_param:
        endpoint_config["incremental"] = {
            "start_param": config.incremental_param,
            "cursor_path": config.incremental_fields[0]["field"],
            "initial_value": INCREMENTAL_INITIAL_VALUE,
            "convert": _format_datetime,
        }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field and config.incremental_param
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _coerce_payload(value: Any) -> Optional[dict[str, Any]]:
    """Read a webhook column back as a dict; the buffering layer JSON-encodes nested values."""
    if isinstance(value, str | bytes):
        try:
            value = orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return parser.parse(value)
    except (ValueError, OverflowError):
        return None


def webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the pull-API table shape.

    Deliveries land as the whole event envelope (`{id, type, createdAt, data, ...}`), so the
    resource object has to be lifted out of `data` — and out of `data.order` for ORDER_UPDATED,
    which nests it one level deeper. Only the newest event per object id survives: delta merge
    dedupes across syncs but not within one batch, so an ORDER_PLACED followed by an
    ORDER_UPDATED for the same order must collapse here.
    """
    if "data" not in table.column_names or "type" not in table.column_names:
        return table_from_py_list([])

    created_at_column = (
        table.column("createdAt").to_pylist() if "createdAt" in table.column_names else [None] * table.num_rows
    )

    latest_by_id: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}
    for event_type, data, event_created_at in zip(
        table.column("type").to_pylist(), table.column("data").to_pylist(), created_at_column
    ):
        row = _coerce_payload(data)
        if row is None:
            continue

        unwrap_key = WEBHOOK_EVENT_DATA_UNWRAP_KEY.get(str(event_type))
        if unwrap_key is not None:
            row = _coerce_payload(row.get(unwrap_key))
            if row is None:
                continue

        row_id = row.get("id")
        if row_id is None:
            continue

        created_at = _parse_datetime(event_created_at)
        existing = latest_by_id.get(row_id)
        # Later rows win ties so batch arrival order breaks equal or unparseable timestamps.
        if existing is None or existing[0] is None or (created_at is not None and created_at >= existing[0]):
            latest_by_id[row_id] = (created_at, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


def fourthwall_source(
    username: str,
    password: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[FourthwallResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FOURTHWALL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(username, password, api_version),
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook fires after a page has been yielded, so a crash re-yields the last page
        # (merge dedupes on the primary key) rather than skipping it. Only persist while a
        # next page remains; the Redis TTL handles cleanup.
        if state:
            resumable_source_manager.save_state(FourthwallResumeConfig(paginator_state=dict(state)))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and endpoint in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=webhook_table_transformer)
        return resource

    partitioned = config.partition_key is not None
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_key,
        sort_mode=config.sort_mode,
        partition_count=1 if partitioned else None,
        partition_size=1 if partitioned else None,
        partition_mode="datetime" if partitioned else None,
        partition_format="month" if partitioned else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _make_session(username: str, password: str) -> Session:
    session = make_tracked_session(
        headers={"Accept": "application/json"},
        redact_values=(password,),
        # Webhook responses can carry the signing secret, so keep them out of sample capture.
        capture=False,
        allow_redirects=False,
    )
    session.auth = (username, password)
    return session


def validate_credentials(username: str, password: str, api_version: str) -> tuple[bool, str | None]:
    """Probe the shop endpoint — the cheapest call that proves the API user is real.

    Fourthwall API users have full access to every Open API endpoint, so one probe validates
    every table this source syncs.
    """
    response = _make_session(username, password).get(
        f"{api_root(api_version)}/shops/current", timeout=REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Fourthwall rejected the API user. Check the username and password and try again."
    if response.status_code == 404:
        return False, "No Fourthwall shop is reachable with this API user."
    return False, f"Fourthwall returned an unexpected status: {response.status_code}"


def _iterate_webhooks(session: Session, api_version: str) -> list[dict[str, Any]]:
    webhooks: list[dict[str, Any]] = []
    page = 0
    while True:
        response = session.get(
            f"{api_root(api_version)}/webhooks",
            params={"page": page, "size": PAGE_SIZE},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
        webhooks.extend(item for item in body.get("results") or [] if isinstance(item, dict))

        total_pages = body.get("totalPages")
        page += 1
        if not isinstance(total_pages, int) or page >= total_pages:
            return webhooks


def _webhooks_matching(session: Session, api_version: str, webhook_url: str) -> list[dict[str, Any]]:
    return [item for item in _iterate_webhooks(session, api_version) if item.get("url") == webhook_url]


def create_webhook(username: str, password: str, api_version: str, webhook_url: str) -> WebhookCreationResult:
    try:
        session = _make_session(username, password)
        response = session.post(
            f"{api_root(api_version)}/webhooks",
            json={"url": webhook_url, "allowedTypes": ALL_WEBHOOK_EVENTS},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code not in (200, 201):
            return WebhookCreationResult(
                success=False,
                error=(
                    f"Fourthwall refused to create the webhook (HTTP {response.status_code}). "
                    "Please create it manually below."
                ),
            )

        # The create response is documented to carry the shop's webhook signing secret, but the
        # published schema for the webhook object does not list it. When it is absent, the user
        # copies the secret from their shop's developer settings instead.
        secret = response.json().get("secret")
        if not secret:
            return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the Fourthwall webhook: {e}. Please create it manually below.",
        )


def sync_webhook_events(
    username: str, password: str, api_version: str, webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Add any missing `desired_events` to the shop's webhook pointing at `webhook_url`.

    Events are merged rather than replaced, so a webhook a user broadened by hand keeps its
    extra events. Fourthwall's update endpoint requires the full url plus event list.
    """
    try:
        session = _make_session(username, password)
        for webhook in _webhooks_matching(session, api_version, webhook_url):
            current = webhook.get("allowedTypes") or []
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue
            response = session.put(
                f"{api_root(api_version)}/webhooks/{webhook.get('id')}",
                json={"url": webhook_url, "allowedTypes": merged},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(success=False, error=f"Failed to update Fourthwall webhook events: {e}")


def get_external_webhook_info(username: str, password: str, api_version: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        matching = _webhooks_matching(_make_session(username, password), api_version, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=matching[0].get("url"),
            enabled_events=matching[0].get("allowedTypes"),
            status="enabled",
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(username: str, password: str, api_version: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _make_session(username, password)
        errors: list[str] = []
        for webhook in _webhooks_matching(session, api_version, webhook_url):
            response = session.delete(
                f"{api_root(api_version)}/webhooks/{webhook.get('id')}", timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code not in (200, 204):
                errors.append(f"webhook {webhook.get('id')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
