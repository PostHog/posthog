import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync
from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.whop.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    PAGE_SIZE,
    WEBHOOK_SCHEMA_NAMES,
    WHOP_ENDPOINTS,
    sort_mode_for,
)

REQUEST_TIMEOUT = 30


@dataclasses.dataclass
class WhopResumeConfig:
    cursor: str


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce a persisted watermark to an aware UTC datetime.

    Whop timestamps are ISO 8601 strings (e.g. "2023-12-01T05:00:00.401Z"), so the stored value is a
    string or datetime; epoch numbers are accepted defensively.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, int | float):
        try:
            return datetime.fromtimestamp(value, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _to_iso8601(value: datetime) -> str:
    """Render a watermark the way Whop's timestamp filters expect (UTC, `Z` suffix)."""
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class WhopCursorPaginator(JSONResponseCursorPaginator):
    """Relay-style cursor paginator for Whop list endpoints.

    Whop returns `{"data": [...], "page_info": {"end_cursor", "has_next_page", ...}}`. Relay keeps
    `end_cursor` populated on the final page, so paging must terminate on `has_next_page` rather
    than on a missing cursor.
    """

    def __init__(self) -> None:
        super().__init__(cursor_path="page_info.end_cursor", cursor_param="after")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not self._has_next_page:
            return
        try:
            page_info = response.json().get("page_info") or {}
        except Exception:
            # An unparseable body means the framework has nothing to page with either; stop rather
            # than re-requesting the same cursor forever.
            self._has_next_page = False
            return
        self._has_next_page = bool(page_info.get("has_next_page"))


def _list_params(
    endpoint: str,
    company_id: str,
    watermark: Optional[datetime],
) -> dict[str, Any]:
    config = WHOP_ENDPOINTS[endpoint]
    params: dict[str, Any] = {"first": PAGE_SIZE, "company_id": company_id}

    if config.supports_created_at_order:
        # Forcing the sort column makes the arrival order knowable, which is what lets this endpoint
        # declare sort_mode="asc" and checkpoint the watermark per batch.
        params["order"] = "created_at"
        params["direction"] = "asc"
    elif config.supports_direction:
        params["direction"] = "desc"

    if watermark is not None and config.supports_created_after:
        params["created_after"] = _to_iso8601(watermark)

    return params


def whop_source(
    api_key: str,
    company_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WhopResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = WHOP_ENDPOINTS[endpoint]
    watermark = _parse_datetime(db_incremental_field_last_value) if should_use_incremental_field else None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": WhopCursorPaginator(),
            # capture=False: Whop list responses carry buyer PII (emails, phone numbers, billing and
            # shipping addresses) and signed invoice tokens the name-based scrubbers can't
            # recognise, so keep the raw bodies out of HTTP sample capture.
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
        },
        "resources": [
            {
                "name": endpoint,
                "write_disposition": {
                    "disposition": "merge",
                    "strategy": "upsert",
                }
                if should_use_incremental_field
                else "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    "params": _list_params(endpoint, company_id, watermark),
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The hook fires AFTER a page is yielded, so a crash re-yields the last page (merge dedupes
        # on `id`) rather than skipping it. Only persist while a next page remains.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(WhopResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The `created_after` filter is already baked into the request params, so the framework's
        # own incremental param injection is intentionally unused.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and endpoint in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=False)

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        sort_mode=sort_mode_for(endpoint),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the pull-API table shape.

    Deliveries land as the full POST body `{"id", "type", "timestamp", "company_id", "data": {...}}`
    where `data` is the resource in the same shape the list endpoint returns. We hoist `data` to the
    row root and keep only the newest version per resource id within the batch - delta merge only
    dedupes across syncs, so a batch carrying e.g. `payment.pending` then `payment.succeeded` for
    one payment must collapse to the latest row here.
    """
    if "data" not in table.column_names:
        return table_from_py_list([])

    has_timestamp = "timestamp" in table.column_names
    payloads = table.column("data").to_pylist()
    timestamps = table.column("timestamp").to_pylist() if has_timestamp else [None] * len(payloads)

    latest_by_id: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}
    for payload, delivered_at in zip(payloads, timestamps):
        # The buffering layer may serialize nested structures back to JSON strings.
        if isinstance(payload, str | bytes):
            try:
                payload = orjson.loads(payload)
            except orjson.JSONDecodeError:
                continue
        if not isinstance(payload, dict) or payload.get("id") is None:
            continue
        sent_at = _parse_datetime(delivered_at)
        existing = latest_by_id.get(payload["id"])
        # Later rows win ties so batch arrival order breaks equal or missing timestamps.
        if existing is None or existing[0] is None or (sent_at is not None and sent_at >= existing[0]):
            latest_by_id[payload["id"]] = (sent_at, payload)

    return table_from_py_list([row for _, row in latest_by_id.values()])


def _make_session(api_key: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        # Webhook responses carry the signing secret, so keep them out of HTTP sample capture.
        capture=False,
    )


def validate_credentials(api_key: str, company_id: str) -> tuple[bool, Optional[int]]:
    """Probe the credential against the connected company, returning `(is_valid, status_code)`.

    `GET /companies/{id}` is the cheapest call that proves both the key and the company id. A 403
    means the key is genuine but lacks `company:basic:read`, which the caller accepts at
    source-create time.
    """
    return validate_via_probe(
        lambda: make_tracked_session(capture=False, redact_values=(api_key,)),
        f"{BASE_URL}/companies/{company_id}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )


def _iterate_webhooks(session: Session, company_id: str) -> Iterator[dict[str, Any]]:
    """Walk `GET /webhooks` with Whop's cursor pagination, yielding each webhook object."""
    cursor: Optional[str] = None
    while True:
        params: dict[str, Any] = {"company_id": company_id, "first": PAGE_SIZE}
        if cursor:
            params["after"] = cursor
        response = session.get(f"{BASE_URL}/webhooks?{urlencode(params)}", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
        yield from (item for item in body.get("data") or [] if isinstance(item, dict))

        page_info = body.get("page_info") or {}
        if not page_info.get("has_next_page"):
            return
        cursor = page_info.get("end_cursor")
        if not cursor:
            return


def _webhooks_matching(session: Session, company_id: str, webhook_url: str) -> list[dict[str, Any]]:
    return [item for item in _iterate_webhooks(session, company_id) if item.get("url") == webhook_url]


def create_webhook(api_key: str, company_id: str, webhook_url: str) -> WebhookCreationResult:
    """Register a v1 webhook on the company, returning Whop's generated signing secret.

    `api_version_date` is deliberately left unset: unpinned v1 deliveries use the payload shape this
    source's transformer expects, and pinning would opt the webhook into the dated Experimental
    contract instead.
    """
    try:
        session = _make_session(api_key)
        response = session.post(
            f"{BASE_URL}/webhooks",
            json={
                "url": webhook_url,
                "events": ALL_WEBHOOK_EVENTS,
                "resource_id": company_id,
                "api_version": "v1",
                "enabled": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in (200, 201):
            return WebhookCreationResult(
                success=False,
                error=(
                    f"Whop rejected the webhook registration (HTTP {response.status_code}). The API key needs the "
                    "developer:manage_webhook permission. Please create the webhook manually below."
                ),
            )

        secret = (response.json() or {}).get("webhook_secret")
        if not secret:
            return WebhookCreationResult(
                success=False,
                error="Whop created the webhook but did not return a signing secret. Please create it manually below.",
            )
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the Whop webhook: {e}. Please create it manually below.",
        )


def sync_webhook_events(
    api_key: str, company_id: str, webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Add any missing `desired_events` to the company's webhooks pointing at `webhook_url`.

    Events are merged, never removed, so a manually broadened webhook keeps its extra events.
    """
    try:
        session = _make_session(api_key)
        for webhook in _webhooks_matching(session, company_id, webhook_url):
            current = webhook.get("events") or []
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue
            response = session.patch(
                f"{BASE_URL}/webhooks/{webhook.get('id')}",
                json={"events": merged},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(success=False, error=f"Failed to update Whop webhook events: {e}")


def get_external_webhook_info(api_key: str, company_id: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        session = _make_session(api_key)
        matching = _webhooks_matching(session, company_id, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)

        webhook = matching[0]
        return ExternalWebhookInfo(
            exists=True,
            url=webhook.get("url"),
            enabled_events=webhook.get("events"),
            status="enabled" if webhook.get("enabled") else "disabled",
            created_at=webhook.get("created_at"),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(api_key: str, company_id: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _make_session(api_key)
        errors: list[str] = []
        for webhook in _webhooks_matching(session, company_id, webhook_url):
            response = session.delete(f"{BASE_URL}/webhooks/{webhook.get('id')}", timeout=REQUEST_TIMEOUT)
            if response.status_code not in (200, 202, 204):
                errors.append(f"webhook {webhook.get('id')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
