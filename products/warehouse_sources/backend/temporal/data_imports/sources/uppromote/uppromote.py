import dataclasses
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import pyarrow as pa
import requests
from asgiref.sync import async_to_sync
from dateutil import parser

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
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.settings import (
    UPPROMOTE_BASE_URL,
    UPPROMOTE_ENDPOINTS,
    UPPROMOTE_OBJECT_TYPE_TO_EVENTS,
    UPPROMOTE_PAGE_SIZE,
    UpPromoteEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class UpPromoteResumeConfig:
    # The next page to fetch (page-number pagination; the API has no pagination metadata).
    page: int
    # Referrals require `from_date` and `to_date` together. The window end is frozen at the
    # first request and carried through resume so a resumed run pages through the same window
    # instead of one that shifted while the job was down.
    to_date: str | None = None


def _format_datetime(value: datetime | date) -> str:
    """Format as ISO 8601 UTC with a Z suffix — the format UpPromote's date filters require."""
    if isinstance(value, datetime):
        utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    else:
        utc_value = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = parser.parse(value)
        except (ValueError, OverflowError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _window_start(last_value: Any) -> str | None:
    """`from_date` for an incremental run: the watermark minus a one-second overlap.

    The docs don't state whether `from_date` is inclusive; re-reading one extra second makes
    either semantic safe — the boundary rows are re-fetched and deduped by the merge.
    """
    coerced = _coerce_datetime(last_value)
    if coerced is None:
        return None
    return _format_datetime(coerced - timedelta(seconds=1))


def _get_headers(api_key: str) -> dict[str, str]:
    # The API key rides raw in the Authorization header — no Bearer prefix (verified in the
    # vendor docs and their own curl examples).
    return {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _make_session(api_key: str) -> requests.Session:
    """Tracked session for webhook-management and credential-probe calls.

    ``capture=False``: affiliate rows carry PII (emails, addresses) and the webhook
    subscription responses carry the signing ``secret_key``; ``redact_values`` masks the API
    key anywhere it appears in logged URLs or headers.
    """
    return make_tracked_session(redact_values=(api_key,), capture=False)


def _extract_message(response: requests.Response) -> str | None:
    try:
        message = response.json().get("message")
    except Exception:
        return None
    return message if isinstance(message, str) else None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """One cheap probe to confirm the API key is genuine.

    UpPromote returns 401 with {"message": "Unauthorized"} (or "Token not provided") for
    missing/invalid keys, verified against the live API.
    """
    url = f"{UPPROMOTE_BASE_URL}/affiliates"
    try:
        response = _make_session(api_key).get(
            url,
            headers=_get_headers(api_key),
            params={"page": 1, "per_page": 1},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return False, f"Could not reach UpPromote: {e}"

    if response.ok:
        return True, None

    if response.status_code == 401:
        return False, (
            "UpPromote rejected the API key. Create a key in the UpPromote app under "
            "Settings > Integrations > API Key (requires the Professional plan) and reconnect."
        )
    return False, _extract_message(response) or f"UpPromote returned status {response.status_code}"


def _build_resource(
    config: UpPromoteEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
    window_end: str | None,
) -> EndpointResource:
    params: dict[str, Any] = {"per_page": UPPROMOTE_PAGE_SIZE}

    # The creation-time window is the only server-side filter UpPromote offers, so the values
    # are known up front and passed as plain params instead of the framework's incremental
    # param indirection. A first incremental run (no watermark) sends no window and pulls
    # everything.
    if should_use_incremental_field and config.supports_date_window and db_incremental_field_last_value is not None:
        from_date = _window_start(db_incremental_field_last_value)
        if from_date is not None:
            params["from_date"] = from_date
            if config.requires_to_date:
                params["to_date"] = window_end

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": config.path,
            "params": params,
        },
        "table_format": "delta",
    }


def _make_webhook_table_transformer(primary_key: str) -> Callable[[pa.Table], pa.Table]:
    """Collapse a webhook batch to the latest version of each object.

    Several events for the same object (e.g. referral.new then referral.approved) can land in
    one batch, and delta merge doesn't dedupe within a batch. Payloads carry no event
    timestamp, but the S3 files are read oldest-first in arrival order, so the last row per
    key is the newest. Rows without the primary key (unexpected shapes) are dropped.
    """

    def transform(table: pa.Table) -> pa.Table:
        latest: dict[Any, dict[str, Any]] = {}
        for row in table.to_pylist():
            key = row.get(primary_key)
            if key is None:
                continue
            latest[key] = row
        return table_from_py_list(list(latest.values()))

    return transform


def uppromote_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[UpPromoteResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = UPPROMOTE_ENDPOINTS[endpoint]
    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    window_end = (
        resume_config.to_date if resume_config and resume_config.to_date else _format_datetime(datetime.now(UTC))
    )

    def items():
        if webhook_enabled:
            return webhook_source_manager.get_items(
                table_transformer=_make_webhook_table_transformer(config.primary_keys[0])
            )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": UPPROMOTE_BASE_URL,
                "auth": {
                    "type": "api_key",
                    "name": "Authorization",
                    "location": "header",
                    "api_key": api_key,
                },
                # Sync responses carry affiliate/referral PII (emails, addresses, payment
                # details), so reuse the capture-disabled, key-redacting tracked session
                # rather than letting RESTClient build its default capturing one.
                "session": _make_session(api_key),
                # No pagination metadata in responses — iterate pages until an empty one.
                "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
            },
            "resource_defaults": {},
            "resources": [
                _build_resource(config, should_use_incremental_field, db_incremental_field_last_value, window_end)
            ],
        }

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Only persist when there's a next page to resume to; the Redis TTL handles
            # cleanup on completion.
            if state and state.get("page"):
                resumable_source_manager.save_state(UpPromoteResumeConfig(page=int(state["page"]), to_date=window_end))

        return rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_keys,
        # The API exposes no sort param and its ordering is undocumented (most likely
        # newest-first). "desc" defers the incremental watermark commit until a sync
        # completes, which is correct for either true ordering; mid-run progress is
        # protected by the resumable page state instead.
        sort_mode="desc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


# --- Webhook management -------------------------------------------------------------------


def all_desired_webhook_events() -> list[str]:
    return [event for events in UPPROMOTE_OBJECT_TYPE_TO_EVENTS.values() for event in events]


def _format_http_error(error: requests.HTTPError) -> str:
    response: requests.Response | None = error.response
    if response is None:
        return str(error)
    return _extract_message(response) or f"UpPromote returned status {response.status_code}"


def _list_subscriptions(session: requests.Session, api_key: str) -> list[dict[str, Any]]:
    response = session.get(
        f"{UPPROMOTE_BASE_URL}/webhook-subscriptions",
        headers=_get_headers(api_key),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("data")
    return data if isinstance(data, list) else []


def _subscribe_missing_events(
    session: requests.Session,
    api_key: str,
    webhook_url: str,
    desired_events: list[str],
) -> tuple[list[str], list[str], str | None]:
    """Ensure each desired event has a subscription pointing at our webhook URL.

    UpPromote allows a single subscription per event (update/delete are keyed by event alone),
    so an event already subscribed to a different URL is left untouched — hijacking it would
    silently break the customer's other integration. Returns (subscribed, taken_by_other_url,
    secret_key).
    """
    subscriptions = _list_subscriptions(session, api_key)
    by_event = {sub.get("event"): sub for sub in subscriptions if sub.get("event")}

    subscribed: list[str] = []
    taken: list[str] = []
    secret: str | None = None

    for event in desired_events:
        existing = by_event.get(event)
        if existing is not None:
            if existing.get("target_url") == webhook_url:
                subscribed.append(event)
                secret = secret or existing.get("secret_key")
            else:
                taken.append(event)
            continue

        response = session.post(
            f"{UPPROMOTE_BASE_URL}/webhook-subscriptions",
            headers=_get_headers(api_key),
            json={"target_url": webhook_url, "event": event},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json().get("data") or {}
        secret = secret or data.get("secret_key")
        subscribed.append(event)

    return subscribed, taken, secret


def create_webhook(api_key: str, webhook_url: str) -> WebhookCreationResult:
    session = _make_session(api_key)
    try:
        subscribed, taken, secret = _subscribe_missing_events(
            session, api_key, webhook_url, all_desired_webhook_events()
        )
    except requests.HTTPError as e:
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except Exception as e:
        return WebhookCreationResult(success=False, error=str(e))

    if not subscribed:
        return WebhookCreationResult(
            success=False,
            error=(
                "Every UpPromote webhook event is already subscribed to a different URL: "
                f"{', '.join(taken)}. UpPromote allows one subscription per event — free up the "
                "events you want PostHog to receive, or set the webhook up manually."
            ),
        )

    extra_inputs: dict[str, Any] = {"signing_secret": secret} if secret else {}
    return WebhookCreationResult(
        success=True,
        extra_inputs=extra_inputs,
        pending_inputs=[] if secret else ["signing_secret"],
    )


def sync_webhook_events(api_key: str, webhook_url: str, desired_events: list[str]) -> WebhookSyncResult:
    session = _make_session(api_key)
    try:
        _, taken, _ = _subscribe_missing_events(session, api_key, webhook_url, desired_events)
    except requests.HTTPError as e:
        return WebhookSyncResult(success=False, error=_format_http_error(e))
    except Exception as e:
        return WebhookSyncResult(success=False, error=str(e))

    if taken:
        return WebhookSyncResult(
            success=False,
            error=(
                "Some UpPromote webhook events are subscribed to a different URL and were left "
                f"untouched: {', '.join(taken)}. UpPromote allows one subscription per event."
            ),
        )
    return WebhookSyncResult(success=True)


def get_external_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    session = _make_session(api_key)
    try:
        subscriptions = _list_subscriptions(session, api_key)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))

    ours = [sub for sub in subscriptions if sub.get("target_url") == webhook_url]
    if not ours:
        return ExternalWebhookInfo(exists=False)

    statuses = {sub.get("status") for sub in ours}
    created_dates = [str(sub["created_at"]) for sub in ours if sub.get("created_at")]
    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        enabled_events=sorted(str(sub.get("event")) for sub in ours),
        status="active" if statuses == {"active"} else "inactive",
        created_at=min(created_dates) if created_dates else None,
    )


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    session = _make_session(api_key)
    try:
        subscriptions = _list_subscriptions(session, api_key)
        ours = [sub for sub in subscriptions if sub.get("target_url") == webhook_url]
        for sub in ours:
            response = session.delete(
                f"{UPPROMOTE_BASE_URL}/webhook-subscriptions",
                headers=_get_headers(api_key),
                json={"event": sub.get("event")},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
    except requests.HTTPError as e:
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))

    if not ours:
        return WebhookDeletionResult(success=False, error="No UpPromote webhook subscriptions point at this URL.")
    return WebhookDeletionResult(success=True)
