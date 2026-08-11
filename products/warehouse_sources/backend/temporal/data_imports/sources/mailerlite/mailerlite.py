import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlsplit

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
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import (
    ALL_WEBHOOK_EVENTS,
    API_VERSION_HEADERS,
    MAILERLITE_ENDPOINTS,
    MAILERLITE_V1,
    WEBHOOK_SCHEMA_NAMES,
)

MAILERLITE_BASE_URL = "https://connect.mailerlite.com/api"

# MailerLite caps list endpoints at 100 rows per page; default is 25.
PAGE_SIZE = 100

WEBHOOK_NAME = "PostHog Data warehouse"


@dataclasses.dataclass
class MailerLiteResumeConfig:
    # Absolute next-page URL returned by the API (carries the cursor / page number and limit).
    next_url: str


class MailerLiteNextUrlPaginator(JSONResponsePaginator):
    """Follows the absolute ``links.next`` URL MailerLite returns for both cursor (subscribers) and
    page-number (everything else) pagination — but only while it stays on the canonical MailerLite
    host. A tampered or compromised response pointing ``next`` off-host is ignored (pagination
    stops after the current page) so our authenticated request can't be redirected to an internal
    address and leak the API key carried in the Authorization header. Off-host *resume* URLs are
    rejected up front by the client's ``allowed_hosts`` guard instead.
    """

    def __init__(self) -> None:
        super().__init__(next_url_path="links.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and (
            not isinstance(self._next_url, str) or not self._next_url.startswith(MAILERLITE_BASE_URL)
        ):
            self._has_next_page = False
            self._next_url = None


def mailerlite_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
    webhook_source_manager: Optional[WebhookSourceManager] = None,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = MAILERLITE_V1,
) -> SourceResponse:
    endpoint_config = MAILERLITE_ENDPOINTS[endpoint]

    # `v1` predates version pinning and sends no header (the exact behaviour existing syncs run
    # under); newer versions pin MailerLite's `X-Version` header so responses stay on a fixed shape.
    headers = {"Accept": "application/json"}
    version_header = API_VERSION_HEADERS.get(api_version)
    if version_header is not None:
        headers["X-Version"] = version_header

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": MAILERLITE_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from
            # logs and raised errors; only the non-secret headers are set here.
            "headers": headers,
            "auth": {"type": "bearer", "token": api_key},
            "paginator": MailerLiteNextUrlPaginator(),
            # Pin every request — including a seeded resume URL — to the MailerLite host so a
            # tampered pagination/resume link can't exfiltrate the Authorization header (SSRF).
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": endpoint_config.path,
                    "params": {"limit": PAGE_SIZE},
                    # Every list response wraps its rows in {"data": [...], "links": {...}, "meta": {...}};
                    # a missing/empty "data" is a legit zero-row page, not an error.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(MailerLiteResumeConfig(next_url=state["next_url"]))

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
        webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)(webhook_only=False)

    def items():
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, path: str = "/subscribers") -> bool:
    """Confirm the API key is genuine with one cheap probe against a list endpoint."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{MAILERLITE_BASE_URL}{path}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok


# Envelope keys a webhook delivery adds around the subscriber object. `event` (flat payloads) and
# `type` (nested ones) name the event, `account_id` identifies the MailerLite account, and
# `subscriber`/`group` only appear on the nested group events — none exist on a polled row.
_WEBHOOK_ENVELOPE_KEYS = frozenset({"event", "type", "account_id", "subscriber", "group"})


def _decode_nested(value: Any) -> Any:
    """Undo the buffering layer's occasional JSON-string serialization of a nested structure."""
    if isinstance(value, str | bytes):
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return value


def _parse_mailerlite_datetime(value: Any) -> Optional[datetime]:
    """Parse a MailerLite timestamp to an aware UTC datetime.

    Webhook deliveries use ISO-8601 ("2024-05-28T10:30:29.000000Z") while the REST API returns a
    space-separated local-looking form ("2024-05-28 10:30:29"); both reach this via a merged
    webhook batch, so accept either and treat a naive value as UTC.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _subscriber_row_from_payload(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Recover the subscriber object from one webhook delivery, in the polled table's shape.

    Flat events (`subscriber.created` and friends) put the subscriber's own fields at the payload
    root; the group events nest the same object under `subscriber`. Either way the envelope keys
    are dropped so a webhook row carries exactly the columns a polled row does.
    """
    nested = _decode_nested(payload.get("subscriber"))
    if isinstance(nested, dict):
        row = {key: value for key, value in nested.items() if key not in _WEBHOOK_ENVELOPE_KEYS}
    else:
        row = {key: value for key, value in payload.items() if key not in _WEBHOOK_ENVELOPE_KEYS}

    return row if row.get("id") is not None else None


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the pull-API table shape.

    Delta merge only dedupes across syncs, so a batch carrying e.g. `subscriber.created` then
    `subscriber.updated` for one subscriber must collapse to the newest row here — otherwise both
    land and every later merge multi-matches them.
    """
    latest_by_id: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}

    for payload in table.to_pylist():
        row = _subscriber_row_from_payload(payload)
        if row is None:
            continue

        updated_at = _parse_mailerlite_datetime(row.get("updated_at"))
        existing = latest_by_id.get(row["id"])
        # Later rows win ties so batch arrival order breaks equal or missing timestamps.
        if existing is None or existing[0] is None or (updated_at is not None and updated_at >= existing[0]):
            latest_by_id[row["id"]] = (updated_at, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


class MailerLiteUntrustedURLError(Exception):
    pass


_API_NETLOC = urlsplit(MAILERLITE_BASE_URL).netloc


def _assert_mailerlite_origin(url: str) -> None:
    """Reject a webhook-management URL that points off the MailerLite API origin.

    `links.next` is response-controlled and this session sends the API key on every request, so a
    poisoned next link (off-host, downgraded to http, or on a non-default port — netloc carries the
    port) would otherwise exfiltrate the key. Redirects are refused separately by the session.
    """
    split = urlsplit(url)
    if not (split.scheme == "https" and split.netloc == _API_NETLOC and split.path.startswith("/api/")):
        raise MailerLiteUntrustedURLError(f"Refusing to follow a MailerLite URL outside {MAILERLITE_BASE_URL}")


def _make_webhook_session(api_key: str) -> Session:
    return make_tracked_session(
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        redact_values=(api_key,),
        # Webhook responses carry the signing secret, so keep the bodies out of HTTP sample
        # capture; no-redirect pins the credentialed request to the origin it validated.
        capture=False,
        allow_redirects=False,
    )


def _iterate_webhooks(session: Session) -> Iterator[dict[str, Any]]:
    next_url: Optional[str] = f"{MAILERLITE_BASE_URL}/webhooks?limit={PAGE_SIZE}"
    while next_url:
        _assert_mailerlite_origin(next_url)
        response = session.get(next_url, timeout=30)
        response.raise_for_status()
        body = response.json()
        yield from (item for item in body.get("data") or [] if isinstance(item, dict))
        next_url = (body.get("links") or {}).get("next")


def _webhooks_matching(session: Session, webhook_url: str) -> list[dict[str, Any]]:
    return [item for item in _iterate_webhooks(session) if item.get("url") == webhook_url]


def create_webhook(api_key: str, webhook_url: str) -> WebhookCreationResult:
    """Register an account-level webhook pointing at `webhook_url`.

    MailerLite generates the signing secret itself and returns it once, on this response — there
    is no way to set or re-read it later, so a create that somehow omits it leaves the user to
    paste one in manually rather than silently ingesting unverified deliveries.
    """
    try:
        session = _make_webhook_session(api_key)
        payload = {
            "name": WEBHOOK_NAME,
            "url": webhook_url,
            "events": ALL_WEBHOOK_EVENTS,
            "enabled": True,
        }
        response = session.post(f"{MAILERLITE_BASE_URL}/webhooks", json=payload, timeout=30)
        if response.status_code not in (200, 201):
            return WebhookCreationResult(
                success=False,
                error=(
                    f"Failed to create the MailerLite webhook (HTTP {response.status_code}). "
                    "Please create it manually below."
                ),
            )

        secret = ((response.json() or {}).get("data") or {}).get("secret")
        if not secret:
            return WebhookCreationResult(success=True, pending_inputs=["signing_secret"])

        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the MailerLite webhook: {e}. Please create it manually below.",
        )


def sync_webhook_events(api_key: str, webhook_url: str, desired_events: list[str]) -> WebhookSyncResult:
    """Add any missing `desired_events` to the webhooks pointing at `webhook_url`.

    Events are merged rather than replaced so a manually broadened webhook keeps its extras.
    """
    try:
        session = _make_webhook_session(api_key)
        for webhook in _webhooks_matching(session, webhook_url):
            current = webhook.get("events") or []
            merged = sorted(set(current) | set(desired_events))
            if merged == sorted(current):
                continue
            response = session.put(
                f"{MAILERLITE_BASE_URL}/webhooks/{webhook.get('id')}",
                json={"events": merged},
                timeout=30,
            )
            response.raise_for_status()
        return WebhookSyncResult(success=True)
    except Exception as e:
        return WebhookSyncResult(success=False, error=f"Failed to update MailerLite webhook events: {e}")


def get_external_webhook_info(api_key: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        session = _make_webhook_session(api_key)
        matching = _webhooks_matching(session, webhook_url)
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


def delete_webhook(api_key: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        session = _make_webhook_session(api_key)
        errors: list[str] = []
        for webhook in _webhooks_matching(session, webhook_url):
            response = session.delete(f"{MAILERLITE_BASE_URL}/webhooks/{webhook.get('id')}", timeout=30)
            if response.status_code not in (200, 204):
                errors.append(f"webhook {webhook.get('id')}: HTTP {response.status_code}")
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
