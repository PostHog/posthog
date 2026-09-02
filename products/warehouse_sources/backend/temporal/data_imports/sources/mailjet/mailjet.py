import base64
import secrets
import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import pyarrow as pa
import structlog
from asgiref.sync import async_to_sync
from requests import Session

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
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import (
    MAILJET_ENDPOINTS,
    MAILJET_WEBHOOK_EVENTS,
    WEBHOOK_PRIMARY_KEY,
    WEBHOOK_TABLE_NAME,
    MailjetEndpointConfig,
)

MAILJET_BASE_URL = "https://api.mailjet.com/v3/REST"
WEBHOOK_PATH = "/eventcallbackurl"
REQUEST_TIMEOUT_SECONDS = 30

# Mailjet does not sign deliveries. Its documented way to prove a delivery came from Mailjet is
# HTTP basic credentials embedded in the registered callback URL, which Mailjet then sends as an
# `Authorization` header on every POST. PostHog generates the password, registers the URL with it
# and stores the expected header on the webhook function.
WEBHOOK_BASIC_AUTH_USERNAME = "posthog"

LOGGER = structlog.get_logger(__name__)


@dataclasses.dataclass
class MailjetResumeConfig:
    offset: int = 0
    # The schema this offset belongs to. A single job can sync multiple schemas, so we
    # guard against applying one endpoint's offset to another on resume.
    endpoint: Optional[str] = None


def _get_headers(api_key: str, secret_key: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:{secret_key}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def _to_unix_ts(value: Any) -> Optional[int]:
    """Convert an incremental field value to a Unix timestamp for Mailjet's FromTS filter."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    return None


def _build_base_params(
    config: MailjetEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    """Build the static query params shared across pages (Sort + optional FromTS window).

    The FromTS value is fixed for the whole sync, so it's a plain static param rather than
    the framework's per-page incremental machinery.
    """
    params: dict[str, Any] = {}
    if config.sort:
        params["Sort"] = config.sort

    if config.from_ts_field and should_use_incremental_field:
        from_ts = _to_unix_ts(db_incremental_field_last_value)
        if from_ts is not None:
            params["FromTS"] = from_ts

    return params


def validate_credentials(api_key: str, secret_key: str) -> bool:
    # /contactmetadata is a small read-only resource — 200 confirms the basic-auth
    # credentials are valid, 401 means they're not.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(secret_key,)),
        f"{MAILJET_BASE_URL}/contactmetadata?Limit=1",
        headers=_get_headers(api_key, secret_key),
    )
    return ok


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Keep one row per ``event_id`` within a batch.

    Delta merge only dedupes across syncs, so a batch that picked up the same delivery twice
    (Mailjet retries until it gets a 200) would otherwise seed duplicate rows. Rows are
    otherwise passed through untouched — Mailjet's event payload is already the row shape.
    """
    rows: dict[str, dict[str, Any]] = {}
    extras: list[dict[str, Any]] = []
    for row in table.to_pylist():
        event_id = row.get(WEBHOOK_PRIMARY_KEY)
        if isinstance(event_id, str) and event_id:
            rows[event_id] = row
        else:
            # Shouldn't happen — the Hog template always sets it — but dropping rows silently
            # would be worse than letting the merge deal with a missing key.
            extras.append(row)

    return table_from_py_list([*rows.values(), *extras])


def _webhook_source(endpoint: str, webhook_source_manager: WebhookSourceManager) -> SourceResponse:
    """The `messageevent` table: fed only by the Event API, never by a poll.

    ``webhook_only`` tells the pipeline the poll does no backfill, so a requested reset keeps the
    Delta table and resumes webhook ingestion instead of wiping rows nothing could rebuild.
    """
    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=True)

    def items() -> Any:
        if not webhook_enabled:
            return []
        return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[WEBHOOK_PRIMARY_KEY],
        webhook_only=True,
        sort_mode="asc",
    )


def mailjet_source(
    api_key: str,
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailjetResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == WEBHOOK_TABLE_NAME:
        return _webhook_source(endpoint, webhook_source_manager)

    config = MAILJET_ENDPOINTS[endpoint]
    limit = config.page_size

    params = _build_base_params(config, should_use_incremental_field, db_incremental_field_last_value)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILJET_BASE_URL,
            # Auth (basic) is supplied via the framework auth config so the secret is redacted
            # from logs and errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": api_key, "password": secret_key},
            "paginator": OffsetPaginator(
                limit=limit,
                offset_param="Offset",
                limit_param="Limit",
                total_path="Total",
            ),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body without `Data` is treated as an empty page (full sync ends),
                    # matching the lenient `data.get("Data") or []` of the previous implementation.
                    "data_selector": "Data",
                },
            }
        ],
    }

    # Resume only if the saved state belongs to this endpoint.
    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.endpoint == endpoint and resume.offset:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(MailjetResumeConfig(offset=int(state["offset"]), endpoint=endpoint))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def _webhook_session(api_key: str, secret_key: str, *redact: str) -> Session:
    return make_tracked_session(
        headers=_get_headers(api_key, secret_key),
        redact_values=(secret_key, *redact),
        # Callback URLs carry the basic-auth password we generated, so keep these responses out
        # of sample capture.
        capture=False,
    )


def _authenticated_callback_url(webhook_url: str, password: str) -> str:
    parts = urlsplit(webhook_url)
    return urlunsplit(
        (parts.scheme, f"{WEBHOOK_BASIC_AUTH_USERNAME}:{password}@{parts.netloc}", parts.path, parts.query, "")
    )


def _without_credentials(url: str) -> str:
    """Strip any `user:password@` prefix so a stored callback URL can be matched against ours."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.rpartition("@")[2], parts.path, parts.query, ""))


def expected_authorization_header(password: str) -> str:
    token = base64.b64encode(f"{WEBHOOK_BASIC_AUTH_USERNAME}:{password}".encode()).decode()
    return f"Basic {token}"


def _list_callback_urls(session: Session) -> list[dict[str, Any]]:
    response = session.get(
        f"{MAILJET_BASE_URL}{WEBHOOK_PATH}",
        # Mailjet defaults this list to 10 rows, which an account with its own callbacks can
        # exceed — ours would then be invisible to matching, so ask for the maximum page.
        params={"Limit": 1000},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [item for item in response.json().get("Data") or [] if isinstance(item, dict)]


def _matching_callback_urls(session: Session, webhook_url: str) -> list[dict[str, Any]]:
    return [
        item for item in _list_callback_urls(session) if _without_credentials(str(item.get("Url", ""))) == webhook_url
    ]


def _register_event(session: Session, callback_url: str, event: str) -> None:
    response = session.post(
        f"{MAILJET_BASE_URL}{WEBHOOK_PATH}",
        json={
            "EventType": event,
            "Url": callback_url,
            "Status": "alive",
            "IsBackup": False,
            # Version 1 posts one event per request. Version 2 batches events into a JSON array,
            # which the warehouse webhook pipeline cannot unpack into rows.
            "Version": 1,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()


def create_webhook(api_key: str, secret_key: str, webhook_url: str) -> WebhookCreationResult:
    """Register one callback URL per Mailjet event type, all pointing at `webhook_url`.

    The registered URL carries generated basic-auth credentials, which Mailjet replays as an
    `Authorization` header on every delivery. The expected header value goes back on the webhook
    function via `extra_inputs` so the Hog template can reject anything else.
    """
    password = secrets.token_urlsafe(32)
    callback_url = _authenticated_callback_url(webhook_url, password)
    session = _webhook_session(api_key, secret_key, password, callback_url)

    registered: list[str] = []
    failures: list[str] = []
    for event in MAILJET_WEBHOOK_EVENTS:
        try:
            _register_event(session, callback_url, event)
            registered.append(event)
        except Exception as e:
            LOGGER.warning("Failed to register Mailjet callback URL", event_type=event, error=str(e))
            failures.append(event)

    if not registered:
        return WebhookCreationResult(
            success=False,
            error="Mailjet refused to register the callback URL. Check that the API key can manage webhooks.",
        )

    if failures:
        # Partial success still has to persist the password: the registrations that landed can
        # only be verified with it, and `sync_webhook_events` reuses the stored URL to fill gaps.
        LOGGER.warning("Registered Mailjet callback URL for some events only", missing=failures)

    return WebhookCreationResult(
        success=True, extra_inputs={"authorization_header": expected_authorization_header(password)}
    )


def sync_webhook_events(
    api_key: str, secret_key: str, webhook_url: str, desired_events: list[str]
) -> WebhookSyncResult:
    """Register any `desired_events` that have no callback URL yet, reusing the credentials
    already on the existing registrations. Never removes an event — a user may have added one."""
    if not desired_events:
        return WebhookSyncResult(success=True)

    try:
        session = _webhook_session(api_key, secret_key)
        matching = _matching_callback_urls(session, webhook_url)
        if not matching:
            # Nothing registered yet; `create_webhook` owns that path.
            return WebhookSyncResult(success=True)

        existing = {str(item.get("EventType")) for item in matching}
        missing = [event for event in desired_events if event not in existing]
        if not missing:
            return WebhookSyncResult(success=True)

        callback_url = str(matching[0].get("Url"))
        for event in missing:
            _register_event(session, callback_url, event)
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(success=False, error=f"Failed to update Mailjet callback URLs: {e}")


def get_external_webhook_info(api_key: str, secret_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        matching = _matching_callback_urls(_webhook_session(api_key, secret_key), webhook_url)
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))

    if not matching:
        return ExternalWebhookInfo(exists=False)

    statuses = {str(item.get("Status")) for item in matching}
    return ExternalWebhookInfo(
        exists=True,
        # Deliberately the credential-free URL — the registered one embeds the shared password.
        url=webhook_url,
        enabled_events=sorted({str(item.get("EventType")) for item in matching}),
        status="alive" if statuses == {"alive"} else ", ".join(sorted(statuses)),
    )


def delete_webhook(api_key: str, secret_key: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _webhook_session(api_key, secret_key)
        errors: list[str] = []
        for item in _matching_callback_urls(session, webhook_url):
            response = session.delete(
                f"{MAILJET_BASE_URL}{WEBHOOK_PATH}/{item.get('ID')}", timeout=REQUEST_TIMEOUT_SECONDS
            )
            if response.status_code not in (200, 204):
                errors.append(f"{item.get('EventType')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
