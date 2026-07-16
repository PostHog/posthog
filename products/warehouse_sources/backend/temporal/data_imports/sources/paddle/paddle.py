import dataclasses
from collections.abc import AsyncIterable, Callable, Iterable
from datetime import UTC, date, datetime, time
from typing import Any, Optional

import orjson
import pyarrow as pa
import requests
import structlog
from asgiref.sync import async_to_sync
from dateutil import parser
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.models.external_table_definitions import get_dlt_mapping_for_external_table
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    DEFAULT_RETRY,
    make_tracked_session,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.constants import (
    PADDLE_AUTO_WEBHOOK_DESCRIPTION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.paddle.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PADDLE_WEBHOOK_EVENTS,
)

LOGGER = structlog.get_logger(__name__)

PADDLE_HOSTS: dict[str, str] = {
    "live": "https://api.paddle.com",
    "sandbox": "https://sandbox-api.paddle.com",
}
PADDLE_BASE_URL = PADDLE_HOSTS["live"]

NOTIFICATION_SETTINGS_PATH = "notification-settings"


def _base_url(environment: Optional[str]) -> str:
    # Unknown or missing values fall back to live: sources created before the environment
    # field existed have no value stored.
    return PADDLE_HOSTS.get(environment or "live", PADDLE_BASE_URL)


@dataclasses.dataclass
class PaddleResumeConfig:
    next_url: str


class PaddlePermissionError(Exception):
    pass


def _format_paddle_datetime_query_value(value: Any) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min, tzinfo=UTC)
    else:
        parsed = parser.isoparse(str(value))

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)

    return parsed.isoformat().replace("+00:00", "Z")


def _get_paddle_session(api_key: str) -> requests.Session:
    # DEFAULT_RETRY backs off on 429/5xx (honoring Retry-After) but leaves auth/4xx
    # failures to surface immediately, so a transient rate-limit doesn't fail the sync.
    # The bearer token is set on the session and registered with redact_values so the
    # tracked transport scrubs it from logged URLs, headers, and captured samples.
    return make_tracked_session(
        retry=DEFAULT_RETRY,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
    )


def paddle_request(session: requests.Session, method: str, url: str, **kwargs) -> requests.Response:
    response = session.request(method, url, **kwargs)
    return response


def get_rows(
    api_key: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    should_use_incremental_field: bool = False,
    environment: str = "live",
):
    url = f"{_base_url(environment)}/{endpoint}"
    params: dict[str, Any] = {"per_page": 200}
    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    params["order_by"] = f"{incremental_field_name}[ASC]" if incremental_field_name else "id[ASC]"

    if should_use_incremental_field and incremental_field_name:
        if db_incremental_field_last_value:
            params[f"{incremental_field_name}[GT]"] = _format_paddle_datetime_query_value(
                db_incremental_field_last_value
            )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config and resume_config.next_url:
        url = resume_config.next_url
        params = {}

    batcher = Batcher(logger=logger)
    session = _get_paddle_session(api_key)
    seen_urls: set[str] = set()

    while url:
        if url in seen_urls:
            break
        seen_urls.add(url)

        response = paddle_request(session, "GET", url, params=params)

        response.raise_for_status()
        data = response.json()

        items = data.get("data", [])

        for item in items:
            batcher.batch(item)

            if batcher.should_yield():
                py_table = batcher.get_table()
                yield py_table

        meta = data.get("meta", {})
        pagination = meta.get("pagination", {})
        next_url = pagination.get("next")
        if next_url == url or next_url in seen_urls:
            next_url = None

        url = next_url
        params = {}

        if batcher.should_yield(include_incomplete_chunk=not url):
            py_table = batcher.get_table()
            if py_table.num_rows > 0:
                yield py_table

        if url:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=url))
        else:
            resumable_source_manager.save_state(PaddleResumeConfig(next_url=""))


def _parse_occurred_at(value: Any) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    if value is None:
        return 0.0
    try:
        return parser.isoparse(str(value)).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _make_webhook_table_transformer(required_field: Optional[str]) -> Callable[[pa.Table], pa.Table]:
    """Build the transformer that reshapes buffered webhook envelopes into entity rows.

    ``required_field`` is the endpoint's incremental cursor (``billed_at`` for transactions, ``None``
    otherwise). Rows missing it are dropped, so the webhook path ingests the same set the pull path
    does — pull filters on ``billed_at[GT]``, which never returns draft (unbilled) transactions — and
    the partition key stays non-null, keeping ``billed_at`` stable across merges.
    """

    def _transform(table: pa.Table) -> pa.Table:
        # Delta merge only dedupes across syncs, so one batch carrying several events for the same
        # entity (e.g. transaction.created then transaction.updated) must be collapsed here to the
        # latest state per id, ordered by the envelope's occurred_at.
        if "data" not in table.column_names:
            return table_from_py_list([])

        data_col = table.column("data").to_pylist()
        occurred_col = (
            table.column("occurred_at").to_pylist() if "occurred_at" in table.column_names else [None] * table.num_rows
        )

        best_by_id: dict[str, tuple[float, dict[str, Any]]] = {}
        for data_value, occurred_at in zip(data_col, occurred_col):
            if data_value is None:
                continue
            # `data` arrives as a struct or a JSON string depending on how the buffering layer
            # serialized the nested envelope — accept both. Skip malformed rows instead of
            # raising: a crash here leaves the S3 file in place and every retry re-crashes on it.
            try:
                entity = orjson.loads(data_value) if isinstance(data_value, (str, bytes)) else dict(data_value)
            except (TypeError, ValueError):
                continue
            if not isinstance(entity, dict):
                continue
            entity_id = entity.get("id")
            if not entity_id:
                continue
            # Drop rows missing the cursor field — draft transactions have no billed_at. Mirrors the
            # pull cursor and guarantees the partition key is never null.
            if required_field is not None and not entity.get(required_field):
                continue
            # occurred_at is RFC3339 with varying fractional precision, so compare parsed
            # timestamps — lexicographic comparison would order "…48.12Z" after "…48.123Z".
            ts = _parse_occurred_at(occurred_at)
            existing = best_by_id.get(entity_id)
            # >= keeps the last-seen event on equal timestamps; S3 files are read oldest-first,
            # so last-seen is the latest arrival.
            if existing is None or ts >= existing[0]:
                best_by_id[entity_id] = (ts, entity)

        return table_from_py_list([entity for _, entity in best_by_id.values()])

    return _transform


def paddle_source(
    api_key: str,
    endpoint: str,
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PaddleResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    environment: str = "live",
) -> SourceResponse:
    column_mapping = get_dlt_mapping_for_external_table(f"paddle_{endpoint.lower()}")
    column_hints = {key: value.get("data_type") for key, value in column_mapping.items()}

    incremental_field_config = INCREMENTAL_FIELDS.get(endpoint, [])
    incremental_field_name = incremental_field_config[0]["field"] if incremental_field_config else None

    # Every Paddle endpoint has a list API, so nothing is webhook-only: the initial sync
    # backfills via the API and later runs read webhook-delivered rows from S3.
    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=False)

    def items() -> Iterable[Any] | AsyncIterable[Any]:
        if webhook_enabled:
            # Drop rows without the cursor field so the webhook path ingests the same set as the pull
            # path (transactions: only billed rows), keeping `billed_at` a stable partition key.
            return webhook_source_manager.get_items(
                table_transformer=_make_webhook_table_transformer(incremental_field_name)
            )
        return get_rows(
            api_key=api_key,
            endpoint=endpoint,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            resumable_source_manager=resumable_source_manager,
            logger=logger,
            environment=environment,
        )

    return SourceResponse(
        items=items,
        primary_keys=["id"],
        name=endpoint,
        column_hints=column_hints,
        sort_mode="asc",
        partition_keys=[incremental_field_name] if incremental_field_name else None,
        partition_mode="datetime" if incremental_field_name else None,
        partition_count=1,
        partition_size=1,
        partition_format="week" if incremental_field_name else None,
    )


def validate_credentials(api_key: str, table_name: Optional[str] = None, environment: str = "live") -> bool:
    endpoints_to_check = [table_name] if table_name else ENDPOINTS
    session = _get_paddle_session(api_key)
    base_url = _base_url(environment)

    for endpoint in endpoints_to_check:
        response = paddle_request(session, "GET", f"{base_url}/{endpoint}")
        if response.status_code == 403:
            raise PaddlePermissionError(f"Missing permissions for {endpoint}")
        response.raise_for_status()

    return True


def _paddle_error_detail(response: Optional[requests.Response]) -> Optional[str]:
    """Pull Paddle's structured error out of a response body.

    Paddle returns `{"error": {"code": ..., "detail": ..., "errors": [{"field", "message"}]}}`.
    Surfacing `detail`/`code` (and per-field messages) turns an opaque status code into an
    actionable message, e.g. "Maximum number of notification settings reached" or the exact
    invalid `subscribed_events` value.
    """
    if response is None:
        return None
    try:
        error = (response.json() or {}).get("error") or {}
    except (ValueError, requests.exceptions.JSONDecodeError):
        return None

    # A non-dict `error` (e.g. an intermediary returning `{"error": "..."}`) would make the
    # `.get()` calls below raise inside the caller's except block, escaping the "never raise"
    # contract of the webhook client functions.
    if not isinstance(error, dict):
        return None

    parts: list[str] = []
    if error.get("detail"):
        parts.append(str(error["detail"]))
    field_errors = error.get("errors")
    if isinstance(field_errors, list):
        for field_error in field_errors:
            if isinstance(field_error, dict) and field_error.get("field") and field_error.get("message"):
                parts.append(f"{field_error['field']}: {field_error['message']}")

    joined = "; ".join(parts)
    code = error.get("code")
    if joined and code:
        return f"{joined} ({code})"
    return joined or code or None


def _format_http_error(error: requests.HTTPError) -> str:
    response = error.response
    status_code = response.status_code if response is not None else None
    detail = _paddle_error_detail(response)

    if status_code == 401:
        base = (
            "Paddle rejected the API key (401). Check that the key is valid and matches the "
            "selected environment (live vs sandbox)."
        )
    elif status_code == 403:
        base = "Paddle denied the request (403). The API key needs write permission for notification settings."
    elif status_code == 404:
        base = "Paddle could not find the notification destination (404)."
    elif status_code == 429:
        base = "Paddle rate-limited the request (429). Try again in a few seconds."
    else:
        base = f"Paddle API error ({status_code})."

    return f"{base} {detail}" if detail else base


def _list_notification_settings(session: requests.Session, base_url: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    url: Optional[str] = f"{base_url}/{NOTIFICATION_SETTINGS_PATH}"
    params: dict[str, Any] = {"per_page": 200}
    seen_urls: set[str] = set()

    while url and url not in seen_urls:
        seen_urls.add(url)
        response = paddle_request(session, "GET", url, params=params)
        response.raise_for_status()
        payload = response.json() or {}

        page = payload.get("data") or []
        if isinstance(page, list):
            items.extend(item for item in page if isinstance(item, dict))

        # `or {}` at each hop: an explicit `"meta": null` (or null pagination) would make a
        # bare `.get("meta", {})` return None and the chained `.get` raise.
        next_url = ((payload.get("meta") or {}).get("pagination") or {}).get("next")
        url = next_url if next_url and next_url not in seen_urls else None
        params = {}

    return items


def _find_notification_setting(session: requests.Session, base_url: str, webhook_url: str) -> Optional[dict[str, Any]]:
    for setting in _list_notification_settings(session, base_url):
        if setting.get("destination") == webhook_url:
            return setting
    return None


def create_webhook(api_key: str, environment: Optional[str], webhook_url: str) -> WebhookCreationResult:
    """Register (or reuse) a Paddle notification destination pointing at ``webhook_url``.

    Idempotent: an existing destination with the same URL is reused — reactivated if it was
    disabled — and its ``endpoint_secret_key`` is returned via ``extra_inputs`` so signature
    verification configures itself without the user copying anything from the Paddle dashboard.
    """
    logger = LOGGER.bind(environment=environment)
    base_url = _base_url(environment)
    session = _get_paddle_session(api_key)

    try:
        existing = _find_notification_setting(session, base_url, webhook_url)
        if existing is not None:
            setting_id = existing.get("id")
            if setting_id and not existing.get("active", True):
                response = paddle_request(
                    session,
                    "PATCH",
                    f"{base_url}/{NOTIFICATION_SETTINGS_PATH}/{setting_id}",
                    json={"active": True},
                )
                response.raise_for_status()
            secret = existing.get("endpoint_secret_key")
            if secret:
                return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
            return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])

        response = paddle_request(
            session,
            "POST",
            f"{base_url}/{NOTIFICATION_SETTINGS_PATH}",
            json={
                "description": PADDLE_AUTO_WEBHOOK_DESCRIPTION,
                "destination": webhook_url,
                "type": "url",
                "subscribed_events": PADDLE_WEBHOOK_EVENTS,
                "active": True,
            },
        )
        response.raise_for_status()
        created = (response.json() or {}).get("data") or {}
    except requests.HTTPError as e:
        logger.warning("Failed to create Paddle notification destination", error=str(e))
        return WebhookCreationResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach Paddle to create notification destination", error=str(e))
        return WebhookCreationResult(success=False, error=f"Could not reach Paddle: {e}")

    secret = created.get("endpoint_secret_key")
    if secret:
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])


def update_webhook_events(
    api_key: str, environment: Optional[str], webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Add ``desired_events`` to the matching destination, writing only on drift.

    Merges (never removes) so user-added subscriptions survive reconciliation. A missing
    destination is a success — creation is handled by ``create_webhook``.
    """
    if not desired_events:
        return WebhookSyncResult(success=True)

    logger = LOGGER.bind(environment=environment)
    base_url = _base_url(environment)
    session = _get_paddle_session(api_key)

    try:
        existing = _find_notification_setting(session, base_url, webhook_url)
        if existing is None:
            return WebhookSyncResult(success=True)

        setting_id = existing.get("id")
        if not setting_id:
            return WebhookSyncResult(success=False, error="Paddle returned a notification destination without an id.")

        # Paddle returns subscribed_events as event-type objects but accepts plain names on write.
        current = {
            event.get("name")
            for event in existing.get("subscribed_events") or []
            if isinstance(event, dict) and event.get("name")
        }
        desired = set(desired_events)
        if desired.issubset(current):
            return WebhookSyncResult(success=True)

        response = paddle_request(
            session,
            "PATCH",
            f"{base_url}/{NOTIFICATION_SETTINGS_PATH}/{setting_id}",
            json={"subscribed_events": sorted(current | desired)},
        )
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to update Paddle notification destination events", error=str(e))
        return WebhookSyncResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach Paddle to update notification destination", error=str(e))
        return WebhookSyncResult(success=False, error=f"Could not reach Paddle: {e}")

    return WebhookSyncResult(success=True)


def delete_webhook(api_key: str, environment: Optional[str], webhook_url: str) -> WebhookDeletionResult:
    logger = LOGGER.bind(environment=environment)
    base_url = _base_url(environment)
    session = _get_paddle_session(api_key)

    try:
        existing = _find_notification_setting(session, base_url, webhook_url)
        if existing is None:
            # Nothing to delete is a success — keep delete idempotent.
            return WebhookDeletionResult(success=True)

        setting_id = existing.get("id")
        if not setting_id:
            return WebhookDeletionResult(
                success=False,
                error="Paddle returned a notification destination without an id; please delete it manually.",
            )

        response = paddle_request(session, "DELETE", f"{base_url}/{NOTIFICATION_SETTINGS_PATH}/{setting_id}")
        if response.status_code == 404:
            return WebhookDeletionResult(success=True)
        response.raise_for_status()
    except requests.HTTPError as e:
        logger.warning("Failed to delete Paddle notification destination", error=str(e))
        return WebhookDeletionResult(success=False, error=_format_http_error(e))
    except requests.RequestException as e:
        logger.warning("Could not reach Paddle to delete notification destination", error=str(e))
        return WebhookDeletionResult(success=False, error=f"Could not reach Paddle: {e}")

    return WebhookDeletionResult(success=True)


def get_external_webhook_info(api_key: str, environment: Optional[str], webhook_url: str) -> ExternalWebhookInfo:
    base_url = _base_url(environment)
    session = _get_paddle_session(api_key)

    try:
        existing = _find_notification_setting(session, base_url, webhook_url)
    except requests.HTTPError as e:
        return ExternalWebhookInfo(exists=False, error=_format_http_error(e))
    except requests.RequestException as e:
        return ExternalWebhookInfo(exists=False, error=f"Could not reach Paddle: {e}")

    if existing is None:
        return ExternalWebhookInfo(exists=False)

    enabled_events = [
        name
        for event in existing.get("subscribed_events") or []
        if isinstance(event, dict) and (name := event.get("name"))
    ]
    return ExternalWebhookInfo(
        exists=True,
        url=existing.get("destination"),
        enabled_events=enabled_events or None,
        status="enabled" if existing.get("active", True) else "disabled",
        description=existing.get("description"),
    )
