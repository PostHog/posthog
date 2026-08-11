import base64
import secrets
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import orjson
import pyarrow as pa
import structlog
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
    BaseNextUrlPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sparkpost.settings import (
    SPARKPOST_ENDPOINTS,
    WEBHOOK_BATCH_KEY,
    WEBHOOK_EVENT_GROUPING,
    WEBHOOK_EVENT_TYPES,
    WEBHOOK_NAME,
    WEBHOOK_SCHEMA_NAMES,
)

LOGGER = structlog.get_logger(__name__)

WEBHOOKS_PATH = "/api/v1/webhooks"
REQUEST_TIMEOUT_SECONDS = 30

# SparkPost runs fully independent US and EU stacks that do not share data; the user picks which one
# their account lives on. The set is a fixed allow-list, so the host can't be retargeted at an
# arbitrary server.
SPARKPOST_HOSTS = {
    "us": "https://api.sparkpost.com",
    "eu": "https://api.eu.sparkpost.com",
}
DEFAULT_REGION = "us"


@dataclasses.dataclass
class SparkPostResumeConfig:
    next_url: str


def base_url(region: Optional[str]) -> str:
    resolved = (region or DEFAULT_REGION).lower()
    return SPARKPOST_HOSTS.get(resolved, SPARKPOST_HOSTS[DEFAULT_REGION])


def _format_from(value: Any) -> str:
    """Format an incremental cursor value for SparkPost's ``from`` filter.

    SparkPost's Events Search API expects ``YYYY-MM-DDTHH:MM`` and treats it as UTC by default. We
    truncate to the minute (the finest granularity the filter accepts); ``from`` is inclusive, so
    the boundary event is re-fetched and deduped on ``event_id`` by the merge.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    elif isinstance(value, str):
        # The stored watermark can come back as an ISO 8601 string; parse it so we still emit the
        # ``YYYY-MM-DDTHH:MM`` SparkPost wants rather than passing e.g. ``2026-01-01T00:00:00Z``
        # through verbatim (which the API rejects). Normalize a trailing ``Z`` for fromisoformat.
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    else:
        return str(value)
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M")


def _is_same_host(url: str, host: str) -> bool:
    """True only for ``https`` URLs whose netloc matches the resolved SparkPost API host."""
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == urlparse(host).netloc


class SparkPostLinksPaginator(BaseNextUrlPaginator):
    """Follows SparkPost's HAL-style ``links: [{"href": ..., "rel": ...}]`` next link.

    The ``next`` href is usually a host-relative path (e.g. ``/api/v1/events/message?cursor=...``);
    it's resolved against the API host and re-pinned to that host (https + exact netloc) so a tampered
    response can't redirect the authenticated request (and its API key) off-host. A missing / off-host
    / non-https next link — or a page that returned no rows — terminates pagination.
    """

    def __init__(self, host: str) -> None:
        super().__init__()
        self._host = host

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        # A page with no rows ends the walk before we even look for a next link, matching the
        # source's "stop as soon as a page returns nothing" behavior.
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = None

        next_url = self._extract_next_url(body)
        if next_url:
            self._next_url = next_url
            self._has_next_page = True
        else:
            self._has_next_page = False

    def _extract_next_url(self, body: Any) -> Optional[str]:
        links = body.get("links") if isinstance(body, dict) else None
        if not isinstance(links, list):
            return None
        for link in links:
            if isinstance(link, dict) and link.get("rel") == "next":
                href = link.get("href")
                if not isinstance(href, str) or not href:
                    return None
                # ``urljoin`` resolves a relative path against the host and leaves an absolute URL
                # as-is; either way we re-pin it to the resolved host so a tampered response can't
                # send our authenticated request at an internal address (SSRF).
                resolved = urljoin(f"{self._host}/", href)
                return resolved if _is_same_host(resolved, self._host) else None
        return None


def _iter_batch_events(batch: Any) -> Iterator[dict[str, Any]]:
    """Yield the message events in one SparkPost delivery.

    A delivery is a JSON array of ``{"msys": {"<grouping>": {...}}}`` entries. Anything that isn't
    a ``message_event`` is skipped: the webhook only subscribes to message-event types, and other
    groupings (relay, A/B test) carry a different shape that can't merge into this table.
    """
    if not isinstance(batch, list):
        return
    for entry in batch:
        msys = entry.get("msys") if isinstance(entry, dict) else None
        if not isinstance(msys, dict):
            continue
        event = msys.get(WEBHOOK_EVENT_GROUPING)
        if isinstance(event, dict):
            yield event


def _normalize_webhook_timestamp(value: Any) -> Any:
    """Restate a pushed ``timestamp`` in the format the Events Search API returns.

    Webhook payloads carry a Unix epoch in seconds (``"1460989507"``) where the REST endpoint
    returns ISO 8601 (``"2016-04-18T14:25:07.000Z"``). ``timestamp`` is both the incremental
    cursor and the datetime partition key, so leaving the epoch form in place would drop pushed
    rows into the unknown-date partition and corrupt the watermark against polled rows.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.isdigit():
        seconds = int(value)
    else:
        return value
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Explode the batched webhook payloads into one row per SparkPost event.

    Delta merge only dedupes across syncs, and SparkPost delivers at least once — the same
    ``event_id`` can arrive twice inside a single batch, either as a retried delivery or across
    two files read into the same batch. SparkPost events are immutable, so any repeat is a copy
    of the same event and last-one-wins keeps exactly one row per id.
    """
    if WEBHOOK_BATCH_KEY not in table.column_names:
        return table

    rows_by_event_id: dict[str, dict[str, Any]] = {}
    for raw_batch in table.column(WEBHOOK_BATCH_KEY).to_pylist():
        if not raw_batch:
            continue
        try:
            batch = orjson.loads(raw_batch)
        except orjson.JSONDecodeError:
            LOGGER.warning("Skipping unparseable SparkPost webhook batch")
            continue

        for event in _iter_batch_events(batch):
            event_id = event.get("event_id")
            if event_id is None:
                continue
            row = dict(event)
            row["timestamp"] = _normalize_webhook_timestamp(row.get("timestamp"))
            rows_by_event_id[str(event_id)] = row

    return table_from_py_list(list(rows_by_event_id.values()))


def sparkpost_source(
    region: Optional[str],
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SparkPostResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SPARKPOST_ENDPOINTS[endpoint]
    host = base_url(region)

    params: dict[str, Any] = {}
    if config.pagination == "cursor":
        # ``cursor=initial`` opts the request into SparkPost's cursor-based pagination; we then walk
        # the ``rel: next`` links it returns.
        params["cursor"] = "initial"
        params["per_page"] = config.per_page

    if config.timestamp_filter_param:
        # Continue from the stored watermark on incremental runs; otherwise seed the first sync with
        # the lookback window (bounded by SparkPost's 10-day event retention).
        if should_use_incremental_field and db_incremental_field_last_value:
            cutoff: Any = db_incremental_field_last_value
        elif config.default_lookback_days:
            cutoff = datetime.now(UTC) - timedelta(days=config.default_lookback_days)
        else:
            cutoff = None
        if cutoff is not None:
            params[config.timestamp_filter_param] = _format_from(cutoff)

    paginator = SparkPostLinksPaginator(host) if config.pagination == "cursor" else SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": host,
            # Only the non-secret Accept header lives here; the API key is supplied verbatim on the
            # Authorization header via the framework auth so its value is redacted from logs/errors.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # SparkPost wraps every list endpoint in ``{"results": [...]}``. A 200 without
                    # ``results`` (or a non-list value) yields no rows and stops — the endpoints are
                    # best-effort and shouldn't fail loud on an empty/absent list.
                    "data_selector": config.data_path,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            # Guard the persisted resume URL — only ever saved from the host-pinned paginator, but
            # re-check so a tampered Redis state can't redirect our authenticated request.
            if not _is_same_host(resume_config.next_url, host):
                raise ValueError(f"SparkPost resume state contains an unexpected URL: {resume_config.next_url!r}")
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded and only while a next page remains — a crash re-yields the
        # last batch (merge dedupes on the primary key) instead of skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(SparkPostResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # ``from`` is injected as a static param above, so the framework's incremental machinery is
        # unused here.
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and endpoint in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items():
        # Webhooks supplement the backfill: the poll runs until the initial sync completes, then
        # the manager takes over and delivers the pushed events.
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(region: Optional[str], api_key: str) -> tuple[bool, str | None]:
    """Validate SparkPost credentials with a single cheap probe against ``/api/v1/account``."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{base_url(region)}/api/v1/account",
        headers={"Authorization": api_key, "Accept": "application/json"},
        # 403 means the key authenticated but lacks the ``Account`` scope this probe uses. The key is
        # genuine, and a user who only grants the per-data-type read scopes (as our caption suggests)
        # shouldn't be blocked from connecting — real per-endpoint scope gaps surface at sync time via
        # get_non_retryable_errors. Only 401 is a definitively bad key.
        ok_statuses=(200, 403),
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Invalid SparkPost API key. Check the API key and selected region, then try again."
    return False, f"SparkPost credential validation failed (status {status})."


def _webhook_session(api_key: str, *extra_redactions: str) -> Session:
    return make_tracked_session(
        headers={"Authorization": api_key, "Accept": "application/json"},
        redact_values=(api_key, *extra_redactions),
        # Webhook responses can echo the delivery credentials, so keep them out of sample capture.
        capture=False,
    )


def _permission_error(status_code: int | None) -> str | None:
    if status_code in (401, 403):
        return (
            "SparkPost rejected the API key while managing the webhook. The key needs the "
            "`Webhooks: Read/Write` permission."
        )
    return None


def _list_webhooks(session: Session, host: str) -> list[dict[str, Any]]:
    """Return every webhook on the account. ``GET /api/v1/webhooks`` is not paginated."""
    response = session.get(f"{host}{WEBHOOKS_PATH}", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json() or {}
    results = body.get("results")
    return [item for item in results if isinstance(item, dict)] if isinstance(results, list) else []


def _webhooks_matching(session: Session, host: str, webhook_url: str) -> list[dict[str, Any]]:
    return [item for item in _list_webhooks(session, host) if item.get("target") == webhook_url]


def create_webhook(region: Optional[str], api_key: str, webhook_url: str) -> WebhookCreationResult:
    """Register an event webhook pointing at ``webhook_url``.

    SparkPost authenticates deliveries with credentials we choose at registration time
    (``auth_type: "basic"``), so PostHog generates a random password and stores the exact
    ``Authorization`` header SparkPost will send. The Hog template rejects any delivery whose
    header doesn't match, which is what keeps the ingest endpoint from being open to the world.
    """
    host = base_url(region)
    username = "posthog"
    password = secrets.token_urlsafe(32)
    header_value = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    try:
        response = _webhook_session(api_key, password, header_value).post(
            f"{host}{WEBHOOKS_PATH}",
            json={
                "name": WEBHOOK_NAME,
                "target": webhook_url,
                "events": WEBHOOK_EVENT_TYPES,
                "auth_type": "basic",
                "auth_credentials": {"username": username, "password": password},
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        LOGGER.warning("Could not reach SparkPost to register webhook", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach SparkPost: {e}")

    if response.status_code not in (200, 201):
        LOGGER.warning("Failed to register SparkPost webhook", status_code=response.status_code)
        error = _permission_error(response.status_code) or (
            f"SparkPost rejected the webhook registration (HTTP {response.status_code})."
        )
        return WebhookCreationResult(success=False, error=error)

    return WebhookCreationResult(success=True, extra_inputs={"authorization_header": header_value})


def sync_webhook_events(
    region: Optional[str], api_key: str, webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Add any missing ``desired_events`` to the webhooks targeting ``webhook_url``.

    Events are merged, never removed, so a manually broadened webhook keeps its extra events.
    SparkPost's ``PUT`` only updates the fields it is given, so the delivery credentials set at
    registration are left untouched.
    """
    host = base_url(region)
    try:
        session = _webhook_session(api_key)
        for webhook in _webhooks_matching(session, host, webhook_url):
            current = [event for event in (webhook.get("events") or []) if isinstance(event, str)]
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue
            response = session.put(
                f"{host}{WEBHOOKS_PATH}/{webhook.get('id')}",
                json={"events": merged},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        LOGGER.warning("Failed to update SparkPost webhook events", error=str(e))
        return WebhookSyncResult(success=False, error=f"Failed to update the SparkPost webhook events: {e}")


def get_external_webhook_info(region: Optional[str], api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        matching = _webhooks_matching(_webhook_session(api_key), base_url(region), webhook_url)
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))

    if not matching:
        return ExternalWebhookInfo(exists=False)

    webhook = matching[0]
    return ExternalWebhookInfo(
        exists=True,
        url=webhook.get("target"),
        enabled_events=webhook.get("events"),
        # SparkPost omits `active` on older webhooks, where it defaults to true.
        status="enabled" if webhook.get("active", True) else "disabled",
        description=webhook.get("name"),
    )


def delete_webhook(region: Optional[str], api_key: str, webhook_url: str) -> WebhookDeletionResult:
    host = base_url(region)
    try:
        session = _webhook_session(api_key)
        errors: list[str] = []
        for webhook in _webhooks_matching(session, host, webhook_url):
            response = session.delete(f"{host}{WEBHOOKS_PATH}/{webhook.get('id')}", timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code not in (200, 202, 204):
                errors.append(f"webhook {webhook.get('id')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        LOGGER.warning("Failed to delete SparkPost webhook", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Failed to delete the SparkPost webhook: {e}")
