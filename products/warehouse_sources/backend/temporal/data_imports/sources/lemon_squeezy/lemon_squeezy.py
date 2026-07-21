import secrets
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync
from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
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
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lemon_squeezy.settings import (
    ALL_WEBHOOK_EVENTS,
    BASE_URL,
    JSON_API_HEADERS,
    LEMON_SQUEEZY_ENDPOINTS,
    PAGE_SIZE,
    WEBHOOK_SCHEMA_NAMES,
)


@dataclasses.dataclass
class LemonSqueezyResumeConfig:
    next_url: str


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce a cursor value to an aware UTC datetime.

    Lemon Squeezy timestamps are ISO-8601 strings (e.g. "2024-01-01T12:00:00.000000Z"), so the
    persisted watermark is a string/datetime; epoch ints are accepted defensively.
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


def _flatten_json_api_item(item: dict[str, Any]) -> dict[str, Any]:
    """Hoist a JSON:API resource's `attributes` to the row root, keeping the top-level `id`.

    Lemon Squeezy attributes never contain an `id` key, so the merge/primary key stays the
    resource id. `relationships`/`links` are dropped — attributes already carry the foreign
    keys (`store_id`, `order_id`, ...) as plain columns.
    """
    attributes = item.get("attributes")
    if not isinstance(attributes, dict):
        return {"id": item.get("id")}
    return {"id": item.get("id"), **attributes}


class LemonSqueezyPaginator(JSONResponsePaginator):
    """Follows the JSON:API `links.next` URL, stopping early on incremental syncs.

    Lemon Squeezy list endpoints return rows newest-first (`created_at` descending, no sort
    param) and expose no server-side timestamp filter, so an incremental sync pages from the
    newest row and halts once an entire page predates the watermark. Boundary-page rows older
    than the watermark are re-yielded; the merge on `id` dedupes them.
    """

    def __init__(self, watermark: Optional[datetime] = None) -> None:
        super().__init__(next_url_path="links.next")
        self._watermark = watermark

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self._watermark is not None and data:
            timestamps = [
                parsed
                for parsed in (
                    _parse_datetime((item.get("attributes") or {}).get("created_at"))
                    for item in data
                    if isinstance(item, dict)
                )
                if parsed is not None
            ]
            # Only stop when every row on the page predates the watermark; unparseable pages
            # keep paging so an upstream format change degrades to a full walk, not data loss.
            if timestamps and max(timestamps) < self._watermark:
                self._next_url = None
                self._has_next_page = False
                return
        super().update_state(response, data)


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid. `/v1/users/me` is a cheap authenticated probe."""
    ok, _status = validate_via_probe(
        # capture=False: `/v1/users/me` returns account data; allow_redirects=False keeps the
        # probe (and its bearer token) pinned to the Lemon Squeezy origin.
        lambda: make_tracked_session(capture=False, allow_redirects=False, redact_values=(api_key,)),
        f"{BASE_URL}/v1/users/me",
        headers={**JSON_API_HEADERS, "Authorization": f"Bearer {api_key}"},
    )
    return ok


def lemon_squeezy_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LemonSqueezyResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = LEMON_SQUEEZY_ENDPOINTS[endpoint]
    watermark = _parse_datetime(db_incremental_field_last_value) if should_use_incremental_field else None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": dict(JSON_API_HEADERS),
            "auth": {"type": "bearer", "token": api_key},
            "paginator": LemonSqueezyPaginator(watermark),
            # capture=False: list responses carry customer PII, redeemable `license_keys.key`
            # values, and signed file/checkout URLs the name-based scrubbers can't recognise, so
            # keep the raw bodies out of HTTP sample capture even when an operator enables it.
            "session": make_tracked_session(capture=False, redact_values=(api_key,)),
            # `links.next` is response-controlled, so pin every paginated and resumed request to
            # the Lemon Squeezy origin and refuse redirects — a poisoned next link can't retarget
            # the bearer token at an attacker-controlled host.
            "allowed_hosts": [],
            "allow_redirects": False,
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
                    "params": {"page[size]": PAGE_SIZE},
                    "data_selector": "data",
                },
                "data_map": _flatten_json_api_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the hook fires AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(LemonSqueezyResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The watermark is enforced client-side by the paginator (no server-side timestamp
        # filter exists), so the framework's incremental param injection is intentionally unused.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and endpoint in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=False)

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        # List endpoints return newest-first, so the incremental watermark is finalized only
        # after a fully successful sync.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
    )


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the pull-API table shape.

    Deliveries land as the full POST body `{"meta": {...}, "data": {<JSON:API resource>}}`.
    We flatten `data` the same way the pull path does ({"id", **attributes}) and keep only
    the newest version per id within the batch — delta merge only dedupes across syncs, so a
    batch carrying e.g. `subscription_created` then `subscription_updated` for the same id
    must collapse to the latest row here.
    """
    if "data" not in table.column_names:
        return table_from_py_list([])

    latest_by_id: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}
    for data in table.column("data").to_pylist():
        # The buffering layer may serialize nested structures to JSON strings.
        if isinstance(data, str | bytes):
            try:
                data = orjson.loads(data)
            except orjson.JSONDecodeError:
                continue
        if not isinstance(data, dict):
            continue
        row = _flatten_json_api_item(data)
        if row.get("id") is None:
            continue
        updated_at = _parse_datetime(row.get("updated_at"))
        existing = latest_by_id.get(row["id"])
        # Later rows win ties so batch arrival order breaks equal/missing timestamps.
        if existing is None or existing[0] is None or (updated_at is not None and updated_at >= existing[0]):
            latest_by_id[row["id"]] = (updated_at, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


class LemonSqueezyUntrustedURLError(Exception):
    pass


# Host and scheme of the Lemon Squeezy API, pinned so a response-controlled `links.next` can't
# retarget a credentialed webhook-management request at another origin.
_API_NETLOC = urlsplit(BASE_URL).netloc


def _assert_lemon_squeezy_origin(url: str) -> None:
    """Reject a webhook-pagination URL that points off the Lemon Squeezy API origin.

    `links.next` is response-controlled and the webhook-management session sends the bearer
    token on every request, so a poisoned next link (off-host, downgraded to http, or on a
    non-default port — netloc carries the port) would otherwise exfiltrate the key. Redirects
    are separately refused by the no-redirect session `_make_session` builds.
    """
    split = urlsplit(url)
    if not (split.scheme == "https" and split.netloc == _API_NETLOC and split.path.startswith("/v1/")):
        raise LemonSqueezyUntrustedURLError(f"Refusing to follow a Lemon Squeezy URL outside {BASE_URL}/v1/")


def _make_session(api_key: str) -> Session:
    return make_tracked_session(
        headers={**JSON_API_HEADERS, "Authorization": f"Bearer {api_key}"},
        redact_values=(api_key,),
        # Webhook responses carry the signing secret and store/customer data, so keep them out of
        # HTTP sample capture; no-redirect pins the credentialed request to the origin it validated.
        capture=False,
        allow_redirects=False,
    )


def _iterate_list(session: Session, url: str) -> Iterator[dict[str, Any]]:
    """Walk a JSON:API list endpoint via `links.next`, yielding each `data[]` item."""
    next_url: Optional[str] = url
    while next_url:
        _assert_lemon_squeezy_origin(next_url)
        response = session.get(next_url, timeout=30)
        response.raise_for_status()
        body = response.json()
        yield from (item for item in body.get("data") or [] if isinstance(item, dict))
        next_url = (body.get("links") or {}).get("next")


def _list_webhooks_matching(session: Session, webhook_url: str) -> list[dict[str, Any]]:
    return [
        item
        for item in _iterate_list(session, f"{BASE_URL}/v1/webhooks?page[size]={PAGE_SIZE}")
        if (item.get("attributes") or {}).get("url") == webhook_url
    ]


def create_webhook(api_key: str, webhook_url: str) -> WebhookCreationResult:
    """Register a webhook pointing at `webhook_url` on every store in the account.

    Lemon Squeezy webhooks are store-scoped, so one is created per store, all sharing a single
    generated signing secret (the hog function only stores one).
    """
    # Lemon Squeezy accepts a 6-40 character signing secret; token_hex(20) is exactly 40.
    secret = secrets.token_hex(20)

    try:
        session = _make_session(api_key)
        stores = list(_iterate_list(session, f"{BASE_URL}/v1/stores?page[size]={PAGE_SIZE}"))
        if not stores:
            return WebhookCreationResult(
                success=False,
                error="No Lemon Squeezy stores found for this API key. Please create the webhook manually.",
            )

        errors: list[str] = []
        created = 0
        for store in stores:
            payload = {
                "data": {
                    "type": "webhooks",
                    "attributes": {
                        "url": webhook_url,
                        "events": ALL_WEBHOOK_EVENTS,
                        "secret": secret,
                    },
                    "relationships": {"store": {"data": {"type": "stores", "id": str(store.get("id"))}}},
                }
            }
            response = session.post(f"{BASE_URL}/v1/webhooks", json=payload, timeout=30)
            if response.status_code in (200, 201):
                created += 1
            else:
                errors.append(f"store {store.get('id')}: HTTP {response.status_code}")

        if created == 0:
            return WebhookCreationResult(
                success=False,
                error=(
                    "Failed to create the Lemon Squeezy webhook "
                    f"({'; '.join(errors)}). Please create it manually below."
                ),
            )

        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the Lemon Squeezy webhook: {e}. Please create it manually below.",
        )


def sync_webhook_events(api_key: str, webhook_url: str, desired_events: list[str]) -> WebhookSyncResult:
    """Add any missing `desired_events` to the account's webhooks pointing at `webhook_url`.

    Events are merged (never removed) so a manually-broadened webhook keeps its extra events.
    """
    try:
        session = _make_session(api_key)
        for webhook in _list_webhooks_matching(session, webhook_url):
            current = (webhook.get("attributes") or {}).get("events") or []
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue
            payload = {
                "data": {
                    "type": "webhooks",
                    "id": str(webhook.get("id")),
                    "attributes": {"events": merged},
                }
            }
            response = session.patch(f"{BASE_URL}/v1/webhooks/{webhook.get('id')}", json=payload, timeout=30)
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(success=False, error=f"Failed to update Lemon Squeezy webhook events: {e}")


def get_external_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        session = _make_session(api_key)
        matching = _list_webhooks_matching(session, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)

        attributes = matching[0].get("attributes") or {}
        return ExternalWebhookInfo(
            exists=True,
            url=attributes.get("url"),
            enabled_events=attributes.get("events"),
            status="enabled",
            created_at=attributes.get("created_at"),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _make_session(api_key)
        matching = _list_webhooks_matching(session, webhook_url)
        errors: list[str] = []
        for webhook in matching:
            response = session.delete(f"{BASE_URL}/v1/webhooks/{webhook.get('id')}", timeout=30)
            if response.status_code not in (200, 204):
                errors.append(f"webhook {webhook.get('id')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
