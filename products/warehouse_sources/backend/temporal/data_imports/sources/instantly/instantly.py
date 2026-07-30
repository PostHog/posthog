import time
import hashlib
import secrets
import dataclasses
from datetime import datetime
from typing import Any, Optional

import orjson
import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.instantly.settings import (
    BASE_URL,
    DEFAULT_PAGE_SIZE,
    EMAILS_REQUEST_INTERVAL_SECONDS,
    INSTANTLY_ENDPOINTS,
    WEBHOOK_EVENTS_ENDPOINT,
    InstantlyEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30
# Bounded walk of the webhook list when reconciling ours by URL — a workspace won't have
# thousands of webhooks, so this is a defensive cap, not an expected limit.
MAX_WEBHOOK_LIST_PAGES = 10

WEBHOOK_NAME = "PostHog data warehouse"
# Instantly deliveries are unsigned, but webhooks accept static custom headers — we attach a
# generated secret header on create and the webhook template verifies it on every delivery.
WEBHOOK_SECRET_HEADER = "x-posthog-webhook-secret"

WEBHOOK_PLAN_ERROR = (
    "Instantly rejected the webhook request because the workspace's plan does not include webhooks "
    "(Hypergrowth plan or above is required). You can keep syncing with scheduled pulls instead."
)
WEBHOOK_SCOPE_ERROR = (
    "Your Instantly API key is not allowed to manage webhooks. Use a key with the `webhooks:all` "
    "(or `all:all`) scope, or set the webhook up manually."
)


@dataclasses.dataclass
class InstantlyResumeConfig:
    cursor: str


class InstantlyCursorPaginator(JSONResponseCursorPaginator):
    """starting_after/next_starting_after cursor pagination.

    Stops on an empty page or a non-advancing cursor — the docs don't state whether the last
    page omits `next_starting_after` or returns it alongside zero items, so guard both.
    """

    def __init__(self, use_json_body: bool = False) -> None:
        if use_json_body:
            super().__init__(cursor_path="next_starting_after", cursor_param="starting_after", param_location="json")
        else:
            super().__init__(cursor_path="next_starting_after", cursor_param="starting_after", param_location="query")

    def update_state(self, response: requests.Response, data: Optional[list[Any]] = None) -> None:
        previous_cursor = self._cursor_value
        super().update_state(response, data)
        if not data or (self._cursor_value is not None and self._cursor_value == previous_cursor):
            self._has_next_page = False


class InstantlyThrottledCursorPaginator(InstantlyCursorPaginator):
    """Cursor paginator that waits between pages, for the rate-limited emails endpoint."""

    def __init__(self, interval_seconds: float) -> None:
        super().__init__()
        self._interval_seconds = interval_seconds

    def update_request(self, request: requests.Request) -> None:
        super().update_request(request)
        if self._has_next_page:
            time.sleep(self._interval_seconds)


def _format_incremental_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _make_paginator(config: InstantlyEndpointConfig) -> InstantlyCursorPaginator:
    if config.name == "emails":
        return InstantlyThrottledCursorPaginator(EMAILS_REQUEST_INTERVAL_SECONDS)
    return InstantlyCursorPaginator(use_json_body=config.method == "POST")


def get_resource(endpoint: str, should_use_incremental_field: bool) -> EndpointResource:
    config = INSTANTLY_ENDPOINTS[endpoint]

    endpoint_config: Endpoint = {
        "path": f"/api/v2{config.path}",
        "method": config.method,
    }
    if config.data_selector is not None:
        endpoint_config["data_selector"] = config.data_selector

    if config.pagination == "single":
        endpoint_config["paginator"] = "single_page"
        endpoint_config["params"] = dict(config.params)
    elif config.method == "POST":
        endpoint_config["paginator"] = _make_paginator(config)
        endpoint_config["json"] = {**config.params, "limit": DEFAULT_PAGE_SIZE}
    else:
        endpoint_config["paginator"] = _make_paginator(config)
        params: dict[str, Any] = {**config.params, "limit": DEFAULT_PAGE_SIZE}
        if config.supports_incremental and should_use_incremental_field:
            params["min_timestamp_created"] = {
                "type": "incremental",
                "cursor_path": "timestamp_created",
                "initial_value": "1970-01-01T00:00:00.000Z",
                "convert": _format_incremental_timestamp,
            }
        endpoint_config["params"] = params

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _webhook_events_table_transformer(table: pa.Table) -> pa.Table:
    """Stamp a deterministic `event_id` onto each webhook payload and de-dupe within the batch.

    Instantly webhook payloads carry no unique id, so the primary key is a content hash — a
    redelivered payload hashes identically and merges away instead of duplicating rows.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in table.to_pylist():
        row = dict(raw_row)
        row.pop("event_id", None)
        event_id = hashlib.sha256(orjson.dumps(row, option=orjson.OPT_SORT_KEYS, default=str)).hexdigest()
        if event_id in seen:
            continue
        seen.add(event_id)
        row["event_id"] = event_id
        rows.append(row)
    return table_from_py_list(rows)


def instantly_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[InstantlyResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == WEBHOOK_EVENTS_ENDPOINT:
        return _webhook_events_source(webhook_source_manager)

    config = INSTANTLY_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        },
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(InstantlyResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def _webhook_events_source(webhook_source_manager: Optional[WebhookSourceManager]) -> SourceResponse:
    webhook_enabled = (
        async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=True)
        if webhook_source_manager is not None
        else False
    )

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_events_table_transformer)
        # Webhook-only resource: there is no pull API for the event stream, so a sync without an
        # enabled webhook has nothing to fetch.
        return iter([])

    return SourceResponse(
        name=WEBHOOK_EVENTS_ENDPOINT,
        items=items,
        primary_keys=["event_id"],
        webhook_only=True,
    )


def _make_session(api_key: str) -> requests.Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )


def _probe_endpoint(session: requests.Session, endpoint: str) -> requests.Response:
    """Cheapest possible authenticated request against one endpoint's scope."""
    if endpoint == WEBHOOK_EVENTS_ENDPOINT:
        return session.get(f"{BASE_URL}/api/v2/webhooks", params={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)

    config = INSTANTLY_ENDPOINTS[endpoint]
    url = f"{BASE_URL}/api/v2{config.path}"
    if config.method == "POST":
        return session.post(url, json={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)
    if config.pagination == "single":
        # Analytics endpoints have no limit param; a one-day window keeps the probe cheap.
        params = {"start_date": "2024-01-01", "end_date": "2024-01-01", "exclude_total_leads_count": "true"}
        return session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    return session.get(url, params={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)


def _error_message(response: requests.Response) -> str | None:
    try:
        message = response.json().get("message")
        return str(message) if message else None
    except Exception:
        return None


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    """Probe the token (schema_name=None) or one endpoint's scope (schema_name set).

    At source-create a 403 is accepted: Instantly API keys are scope-gated per resource, and a
    key legitimately scoped to only the tables the user wants must not block the whole source.
    """
    if not api_key:
        return False, "Missing Instantly API key"

    session = _make_session(api_key)
    try:
        response = _probe_endpoint(session, schema_name or "campaigns")
    except Exception as e:
        return False, f"Could not connect to Instantly: {e}"

    if response.status_code == 401:
        return False, "Instantly rejected the API key. Check the key is correct and has not been revoked."
    if response.status_code == 402:
        return False, (
            "Your Instantly workspace does not have an active plan with API access "
            "(the API requires the Growth plan or above)."
        )
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        message = _error_message(response)
        return False, (
            f"Your Instantly API key is missing the scope required for this table"
            f"{f': {message}' if message else '. Grant the matching read scope and try again.'}"
        )
    if not response.ok:
        return False, f"Instantly returned HTTP {response.status_code}"
    return True, None


def get_endpoint_permissions(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table scope status for the schema picker. Only a real denial counts as missing scope."""
    session = _make_session(api_key)
    permissions: dict[str, str | None] = {}
    for endpoint in endpoints:
        try:
            response = _probe_endpoint(session, endpoint)
        except Exception:
            # A network blip is not a permission denial.
            permissions[endpoint] = None
            continue
        if response.status_code in (401, 403):
            message = _error_message(response)
            permissions[endpoint] = message or "Your Instantly API key does not grant access to this table."
        else:
            permissions[endpoint] = None
    return permissions


def _list_webhooks(session: requests.Session, logger: FilteringBoundLogger) -> list[dict[str, Any]]:
    webhooks: list[dict[str, Any]] = []
    starting_after: Optional[str] = None
    for _ in range(MAX_WEBHOOK_LIST_PAGES):
        params: dict[str, Any] = {"limit": DEFAULT_PAGE_SIZE}
        if starting_after:
            params["starting_after"] = starting_after
        response = session.get(f"{BASE_URL}/api/v2/webhooks", params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            break
        webhooks.extend(item for item in items if isinstance(item, dict))
        next_cursor = data.get("next_starting_after") if isinstance(data, dict) else None
        if not next_cursor or next_cursor == starting_after:
            break
        starting_after = next_cursor
    else:
        logger.warning(f"Instantly: webhook listing hit the {MAX_WEBHOOK_LIST_PAGES}-page cap; stopping")
    return webhooks


def _find_webhook_by_url(
    session: requests.Session, webhook_url: str, logger: FilteringBoundLogger
) -> dict[str, Any] | None:
    return next((wh for wh in _list_webhooks(session, logger) if wh.get("target_hook_url") == webhook_url), None)


def create_webhook(api_key: str, webhook_url: str, logger: FilteringBoundLogger) -> WebhookCreationResult:
    try:
        session = _make_session(api_key)
        secret = secrets.token_urlsafe(32)
        body = {
            "target_hook_url": webhook_url,
            "name": WEBHOOK_NAME,
            # all_events also covers custom label events.
            "event_type": "all_events",
            "headers": {WEBHOOK_SECRET_HEADER: secret},
        }

        existing = _find_webhook_by_url(session, webhook_url, logger)
        if existing is not None and existing.get("id") is not None:
            # A webhook for this URL already exists (e.g. a partial earlier setup) — reconcile it
            # with a fresh secret instead of creating a duplicate.
            response = session.patch(
                f"{BASE_URL}/api/v2/webhooks/{existing['id']}", json=body, timeout=REQUEST_TIMEOUT_SECONDS
            )
        else:
            response = session.post(f"{BASE_URL}/api/v2/webhooks", json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 402:
            return WebhookCreationResult(success=False, error=WEBHOOK_PLAN_ERROR)
        if response.status_code in (401, 403):
            return WebhookCreationResult(success=False, error=WEBHOOK_SCOPE_ERROR)
        if not response.ok:
            raise Exception(f"Instantly webhook creation failed with HTTP {response.status_code}")
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        logger.exception(f"Instantly: failed to create webhook: {e}")
        return WebhookCreationResult(success=False, error=f"Failed to create Instantly webhook automatically: {e}")


def get_external_webhook_info(api_key: str, webhook_url: str, logger: FilteringBoundLogger) -> ExternalWebhookInfo:
    try:
        session = _make_session(api_key)
        existing = _find_webhook_by_url(session, webhook_url, logger)
        if existing is None:
            return ExternalWebhookInfo(exists=False)
        # status: 1 = active, -1 = disabled after repeated delivery failures.
        status = "error" if existing.get("status") == -1 else "enabled"
        event_type = existing.get("event_type")
        return ExternalWebhookInfo(
            exists=True,
            url=existing.get("target_hook_url"),
            enabled_events=[event_type] if event_type else None,
            status=status,
            created_at=existing.get("timestamp_created"),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check Instantly webhook: {e}")


def delete_webhook(api_key: str, webhook_url: str, logger: FilteringBoundLogger) -> WebhookDeletionResult:
    try:
        session = _make_session(api_key)
        existing = _find_webhook_by_url(session, webhook_url, logger)
        if existing is None or existing.get("id") is None:
            # Nothing to delete — the desired end state already holds.
            return WebhookDeletionResult(success=True)

        response = session.delete(f"{BASE_URL}/api/v2/webhooks/{existing['id']}", timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code in (401, 403):
            return WebhookDeletionResult(success=False, error=WEBHOOK_SCOPE_ERROR)
        if not response.ok:
            raise Exception(f"Instantly webhook deletion failed with HTTP {response.status_code}")
        return WebhookDeletionResult(success=True)
    except Exception as e:
        logger.exception(f"Instantly: failed to delete webhook: {e}")
        return WebhookDeletionResult(success=False, error=f"Failed to delete Instantly webhook: {e}")
