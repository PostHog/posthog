"""Postmark (ActiveCampaign) transactional email source.

Postmark exposes a REST/JSON API at https://api.postmarkapp.com. Server-level resources
(messages, bounces, templates, message streams) authenticate with a per-server token sent
in the `X-Postmark-Server-Token` header.

Sync is full-refresh only. Postmark's list endpoints accept `fromdate`/`todate` filters
(date granularity, `YYYY-MM-DD`), but we have not been able to verify server-side filtering
against a live token, so we do not advertise incremental sync — matching how the existing
third-party connectors (Airbyte, Fivetran) treat Postmark. Within a sync, pagination is
resumable via the saved offset.

Two upstream constraints worth knowing about:
- The paginated list endpoints cap `count + offset` at 10,000, so a full refresh can only
  reach the most recent 10,000 rows of each. We log a warning when that window is hit.
- Messages expire from Postmark after a retention window (45 days by default), so historical
  data beyond that window is simply unavailable from the API.
"""

import logging
import secrets
import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

import pyarrow as pa
from asgiref.sync import async_to_sync
from dateutil import parser as dateutil_parser
from requests import Response, Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
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
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.postmark.settings import (
    POSTMARK_ENDPOINTS,
    POSTMARK_MAX_PAGE_SIZE,
    POSTMARK_MAX_WINDOW,
    WEBHOOK_MESSAGE_STREAM,
    WEBHOOK_ONLY_FIELDS,
    WEBHOOK_SCHEMA_NAMES,
    WEBHOOK_SECRET_HEADER,
    WEBHOOK_TRIGGERS,
)

logger = logging.getLogger(__name__)

POSTMARK_BASE_URL = "https://api.postmarkapp.com"

REQUEST_TIMEOUT_SECONDS = 30

WEBHOOK_AUTH_ERROR = (
    "Your Postmark server API token can't manage webhooks. Webhooks are managed with a server "
    "token for the server you're syncing, so check the token and try again."
)


@dataclasses.dataclass
class PostmarkResumeConfig:
    # Offset of the next page to fetch on paginated list endpoints.
    next_offset: int = 0


class _WindowCappedOffsetPaginator(OffsetPaginator):
    """OffsetPaginator that warns when it stops because it hit Postmark's 10,000-row window.

    Postmark caps `count + offset` at 10,000 on its paginated list endpoints, so a full
    refresh can only reach the most recent 10,000 rows. `maximum_offset` handles the stop;
    this subclass adds the same diagnostic warning the hand-rolled loop emitted so an
    operator can see that older rows were left behind rather than silently dropped.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        # Only the maximum_offset boundary sets offset >= maximum_offset on stop; a short/empty
        # page stops with offset still below the window (see OffsetPaginator.update_state).
        if not self.has_next_page and self.maximum_offset is not None and self.offset >= self.maximum_offset:
            total: Any = None
            try:
                total = response.json().get("TotalCount")
            except Exception:
                pass
            logger.warning(
                f"Postmark: reached the {self.maximum_offset}-row API window (TotalCount={total}); "
                "older rows cannot be synced via this endpoint."
            )


def _get_headers(server_token: str) -> dict[str, str]:
    return {
        "X-Postmark-Server-Token": server_token,
        "Accept": "application/json",
    }


def validate_credentials(server_token: str) -> tuple[bool, int | None]:
    # /message-streams is a cheap read-only call any valid server token can make. Postmark
    # returns 401 (ErrorCode 10) for an invalid/missing token and 200 otherwise. Return the
    # status so the caller can tell a rejected token (401) from a permissions problem (403) or
    # an unreachable/erroring API (None/5xx), rather than reporting them all as "invalid token".
    return validate_via_probe(
        # `X-Postmark-Server-Token` is not in the sample-capture header denylist, so mask the
        # token by value to keep it out of any captured HTTP sample.
        lambda: make_tracked_session(redact_values=(server_token,)),
        f"{POSTMARK_BASE_URL}/message-streams",
        headers=_get_headers(server_token),
    )


def postmark_source(
    server_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PostmarkResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
) -> SourceResponse:
    config = POSTMARK_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    initial_paginator_state: Optional[dict[str, Any]] = None
    resume_hook = None

    if config.page_size is None:
        # Flat endpoints return their whole payload in a single response.
        paginator: Any = SinglePagePaginator()
    else:
        # Offset/count pagination capped at the 10,000-row API window. `count` is Postmark's
        # per-page size param; termination is a short/empty page or the window boundary.
        page_size = min(config.page_size, POSTMARK_MAX_PAGE_SIZE)
        paginator = _WindowCappedOffsetPaginator(
            limit=page_size,
            offset_param="offset",
            limit_param="count",
            total_path=None,
            maximum_offset=POSTMARK_MAX_WINDOW,
        )

        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                initial_paginator_state = {"offset": resume.next_offset}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash
            # re-yields the last page (merge dedupes) rather than skipping it.
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(PostmarkResumeConfig(next_offset=int(state["offset"])))

        resume_hook = save_checkpoint

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": POSTMARK_BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {
                "type": "api_key",
                "api_key": server_token,
                "name": "X-Postmark-Server-Token",
                "location": "header",
            },
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # full refresh only — no incremental watermark
        resume_hook=resume_hook,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = False
    if webhook_source_manager is not None and endpoint in WEBHOOK_SCHEMA_NAMES:
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=False)

    def items() -> Any:
        # Webhooks only take over once the backfill has completed, so the pull path stays the
        # way every table is first populated.
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _parse_bounced_at(value: Any) -> Optional[datetime]:
    """Coerce a Postmark `BouncedAt` value to an aware UTC datetime.

    Postmark serializes .NET timestamps with up to seven fractional digits
    ("2019-11-05T16:33:54.9070259Z"), which `datetime.fromisoformat` rejects.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dateutil_parser.isoparse(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the Bounce API table shape.

    Bounce and SpamComplaint deliveries carry the bounce record at the top level with the same
    field names the Bounce API returns, so the only reshaping needed is dropping the two
    webhook-only fields. Rows are then collapsed to the newest per `ID` — delta merge only
    dedupes across syncs, so a batch that carries the same record twice (a redelivery) has to
    collapse here.
    """
    latest_by_id: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}
    for raw_row in table.to_pylist():
        row = {key: value for key, value in raw_row.items() if key not in WEBHOOK_ONLY_FIELDS}
        row_id = row.get("ID")
        if row_id is None:
            continue
        bounced_at = _parse_bounced_at(row.get("BouncedAt"))
        existing = latest_by_id.get(row_id)
        # Later rows win ties so batch arrival order breaks equal or missing timestamps.
        if existing is None or existing[0] is None or (bounced_at is not None and bounced_at >= existing[0]):
            latest_by_id[row_id] = (bounced_at, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


def _webhook_management_session(server_token: str) -> Session:
    return make_tracked_session(
        headers={**_get_headers(server_token), "Content-Type": "application/json"},
        # Webhook objects echo back the HttpHeaders we set, which carry the shared secret, so
        # keep these responses out of HTTP sample capture.
        capture=False,
        redact_values=(server_token,),
    )


def _postmark_error(response: Response) -> str | None:
    """Postmark reports API failures as a JSON body with a non-zero `ErrorCode`."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict) or not body.get("ErrorCode"):
        return None
    message = body.get("Message")
    return str(message) if message else f"Postmark error code {body['ErrorCode']}"


def _list_webhooks(session: Session) -> list[dict[str, Any]]:
    # A server holds a handful of webhooks and the endpoint is not paginated.
    response = session.get(f"{POSTMARK_BASE_URL}/webhooks", timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    body = response.json()
    webhooks = body.get("Webhooks") if isinstance(body, dict) else None
    if not isinstance(webhooks, list):
        return []
    return [webhook for webhook in webhooks if isinstance(webhook, dict)]


def _find_webhook_by_url(session: Session, webhook_url: str) -> dict[str, Any] | None:
    return next((webhook for webhook in _list_webhooks(session) if webhook.get("Url") == webhook_url), None)


def create_webhook(server_token: str, webhook_url: str) -> WebhookCreationResult:
    try:
        session = _webhook_management_session(server_token)
        secret = secrets.token_urlsafe(32)
        body: dict[str, Any] = {
            "Url": webhook_url,
            "MessageStream": WEBHOOK_MESSAGE_STREAM,
            "HttpHeaders": [{"Name": WEBHOOK_SECRET_HEADER, "Value": secret}],
            "Triggers": WEBHOOK_TRIGGERS,
        }

        existing = _find_webhook_by_url(session, webhook_url)
        if existing is not None and existing.get("ID") is not None:
            # A webhook for this URL already exists (e.g. a partial earlier setup) — reconcile it
            # with a fresh secret instead of creating a duplicate.
            response = session.put(
                f"{POSTMARK_BASE_URL}/webhooks/{existing['ID']}", json=body, timeout=REQUEST_TIMEOUT_SECONDS
            )
        else:
            response = session.post(f"{POSTMARK_BASE_URL}/webhooks", json=body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code in (401, 403):
            return WebhookCreationResult(success=False, error=WEBHOOK_AUTH_ERROR)
        error = _postmark_error(response)
        if not response.ok or error:
            raise Exception(error or f"Postmark webhook creation failed with HTTP {response.status_code}")
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        logger.exception(f"Postmark: failed to create webhook: {e}")
        return WebhookCreationResult(
            success=False, error=f"Failed to create the Postmark webhook: {e}. Please create it manually below."
        )


def get_external_webhook_info(server_token: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        session = _webhook_management_session(server_token)
        existing = _find_webhook_by_url(session, webhook_url)
        if existing is None:
            return ExternalWebhookInfo(exists=False)

        raw_triggers = existing.get("Triggers")
        triggers: dict[str, Any] = raw_triggers if isinstance(raw_triggers, dict) else {}
        enabled_events = [
            name for name, trigger in triggers.items() if isinstance(trigger, dict) and trigger.get("Enabled")
        ]
        return ExternalWebhookInfo(
            exists=True,
            url=existing.get("Url"),
            enabled_events=enabled_events,
            status="enabled",
            description=f"Message stream: {existing.get('MessageStream')}" if existing.get("MessageStream") else None,
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=f"Failed to check the Postmark webhook: {e}")


def delete_webhook(server_token: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _webhook_management_session(server_token)
        existing = _find_webhook_by_url(session, webhook_url)
        if existing is None or existing.get("ID") is None:
            # Nothing to delete — the desired end state already holds.
            return WebhookDeletionResult(success=True)

        response = session.delete(f"{POSTMARK_BASE_URL}/webhooks/{existing['ID']}", timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code in (401, 403):
            return WebhookDeletionResult(success=False, error=WEBHOOK_AUTH_ERROR)
        error = _postmark_error(response)
        if not response.ok or error:
            raise Exception(error or f"Postmark webhook deletion failed with HTTP {response.status_code}")
        return WebhookDeletionResult(success=True)
    except Exception as e:
        logger.exception(f"Postmark: failed to delete webhook: {e}")
        return WebhookDeletionResult(success=False, error=f"Failed to delete the Postmark webhook: {e}")
