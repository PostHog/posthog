import re
import secrets
import datetime
import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import pyarrow as pa
import structlog
from asgiref.sync import async_to_sync
from dateutil import parser as dateutil_parser
from requests import Session
from requests.exceptions import HTTPError, RequestException

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
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import (
    PipedriveEndpointConfig,
    endpoints_for_version,
)

LOGGER = structlog.get_logger(__name__)

# Pipedrive caps list pages at 500 items (default 100).
PAGE_SIZE = 500

# Webhook management lives on v1; there is no v2 equivalent.
WEBHOOKS_PATH = "/api/v1/webhooks"
# The payload format we register. v2 deliveries carry the entity under `data` in the same shape
# the API v2 collections return, which is what lets pushed rows merge into the polled tables.
WEBHOOK_PAYLOAD_VERSION = "2.0"
WEBHOOK_NAME = "PostHog data warehouse"
# Pipedrive echoes the basic auth credentials set on the subscription back on every delivery.
# The username is fixed and the password is the generated secret.
WEBHOOK_AUTH_USER = "posthog"
WEBHOOK_REQUEST_TIMEOUT_SECONDS = 30

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9-]+$")

# Never reflects the raw input back: it can be a full URL or website domain the user pasted by
# mistake, and echoing it gives no guidance on what a valid value looks like.
_INVALID_COMPANY_DOMAIN_ERROR = (
    "Invalid Pipedrive company domain. Enter just your Pipedrive subdomain — the part before "
    ".pipedrive.com (for example, enter 'acme' for acme.pipedrive.com) — not a full URL or your "
    "website's domain."
)


@dataclasses.dataclass
class PipedriveResumeConfig:
    # Legacy field written by the hand-rolled paginator: the full next-page URL. Kept (optional,
    # defaulted) so previously saved resume state still parses via ``dataclass(**saved)``. No longer
    # written; a resume that carries only this restarts the endpoint from the beginning (merge
    # dedupes any re-yielded rows).
    next_url: Optional[str] = None
    # Framework paginator resume snapshot: ``{"offset": N}`` for v1 offset endpoints or
    # ``{"cursor": "…"}`` for v2 cursor endpoints. Seeds ``initial_paginator_state`` on resume.
    paginator_state: Optional[dict[str, Any]] = None


def normalize_company_domain(raw: str) -> str:
    """Reduce whatever the user typed to the bare Pipedrive subdomain.

    Accepts ``mycompany``, ``mycompany.pipedrive.com`` or ``https://mycompany.pipedrive.com``.
    Raises ``ValueError`` if the result isn't a plain subdomain, which also pins outbound
    traffic to ``*.pipedrive.com`` (no SSRF to arbitrary hosts).
    """
    domain = raw.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    domain = domain.removesuffix(".pipedrive.com")
    if not _SUBDOMAIN_RE.match(domain):
        raise ValueError(_INVALID_COMPANY_DOMAIN_ERROR)
    return domain


def base_url(company_domain: str) -> str:
    return f"https://{normalize_company_domain(company_domain)}.pipedrive.com"


def _get_headers(api_token: str) -> dict[str, str]:
    return {"x-api-token": api_token, "Accept": "application/json"}


def _build_url(company_domain: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    url = f"{base_url(company_domain)}{path}"
    if not clean_params:
        return url
    return f"{url}?{urlencode(clean_params)}"


def _build_paginator(config: PipedriveEndpointConfig) -> BasePaginator:
    if config.pagination == "cursor":
        # v2 endpoints: opaque cursor in the response body; ``limit`` rides in the endpoint params.
        return JSONResponseCursorPaginator(cursor_path="additional_data.next_cursor", cursor_param="cursor")
    # v1 endpoints: start/limit offset. No top-level total; termination is a short/empty page.
    return OffsetPaginator(
        limit=PAGE_SIZE,
        offset=0,
        offset_param="start",
        limit_param="limit",
        total_path=None,
        stop_after_empty_page=True,
    )


def validate_credentials(company_domain: str, api_token: str) -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or ``None`` on transport error.

    ``/api/v1/users/me`` resolves the token's own user and is reachable by any valid token.
    """
    # Built outside the probe so an invalid-domain `ValueError` from `_build_url` propagates to the
    # caller rather than being swallowed into `None` by the probe's broad transport-error handler.
    url = _build_url(company_domain, "/api/v1/users/me", {})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        url,
        headers=_get_headers(api_token),
    )
    return status


def _coerce_payload(value: Any) -> Optional[dict[str, Any]]:
    """Webhook payload blocks arrive as dicts, or as JSON strings once buffered through parquet."""
    if isinstance(value, str | bytes):
        try:
            value = orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _parse_timestamp(value: Any) -> Optional[datetime.datetime]:
    if not isinstance(value, str):
        return None
    try:
        return dateutil_parser.parse(value)
    except (ValueError, OverflowError):
        return None


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape raw webhook deliveries into rows matching the pull-API table shape.

    A delivery lands as the whole v2 envelope (`{"meta": {...}, "data": {...}, "previous": {...}}`),
    so the entity has to be lifted out of `data`. Only the newest delivery per id survives: delta
    merge dedupes across syncs but not within one batch, so a `create` followed by a `change` for
    the same deal must collapse here or the batch would merge the same key twice.
    """
    if "data" not in table.column_names:
        return table_from_py_list([])

    meta_column = table.column("meta").to_pylist() if "meta" in table.column_names else [None] * table.num_rows

    latest_by_id: dict[Any, tuple[Optional[datetime.datetime], dict[str, Any]]] = {}
    for data, meta in zip(table.column("data").to_pylist(), meta_column):
        row = _coerce_payload(data)
        if row is None:
            continue

        row_id = row.get("id")
        if row_id is None:
            continue

        meta_row = _coerce_payload(meta) or {}
        # The Hog template already drops deletions; this keeps a hand-configured webhook that
        # subscribed to them from blanking a polled row with a tombstone payload.
        if meta_row.get("action") == "delete":
            continue

        timestamp = _parse_timestamp(meta_row.get("timestamp"))
        existing = latest_by_id.get(row_id)
        # Later rows win ties so batch arrival order breaks equal or unparseable timestamps.
        if existing is None or existing[0] is None or (timestamp is not None and timestamp >= existing[0]):
            latest_by_id[row_id] = (timestamp, row)

    return table_from_py_list([row for _, row in latest_by_id.values()])


def _webhook_error_result(action: str, error: Exception, status_code: Optional[int]) -> str:
    LOGGER.warning(f"Failed to {action} Pipedrive webhook", error=str(error), status_code=status_code)
    if status_code in (401, 403):
        return (
            "Pipedrive rejected the API token while managing the webhook. The token's user needs "
            "permission to manage webhooks."
        )
    if status_code is not None:
        return f"Pipedrive API error ({status_code})."
    return f"Could not reach Pipedrive: {error}"


def _webhooks_url(company_domain: str, webhook_id: Optional[int] = None) -> str:
    path = WEBHOOKS_PATH if webhook_id is None else f"{WEBHOOKS_PATH}/{webhook_id}"
    return _build_url(company_domain, path, {})


def _list_webhooks(company_domain: str, api_token: str) -> list[dict[str, Any]]:
    session = make_tracked_session(redact_values=(api_token,))
    response = session.get(
        _webhooks_url(company_domain),
        headers=_get_headers(api_token),
        timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json().get("data")
    return [hook for hook in data if isinstance(hook, dict)] if isinstance(data, list) else []


def create_webhook(company_domain: str, api_token: str, webhook_url: str) -> WebhookCreationResult:
    """Register one wildcard webhook (`event_action="*"`, `event_object="*"`) on the account.

    Pipedrive scopes a subscription to a single action/object pair, so a per-entity subscription
    would burn one of the account's 40 webhook slots per table. The Hog template drops every
    entity that isn't mapped to a selected schema before anything is persisted, and the wildcard
    can't drift out of sync when the user enables another table later.
    """
    password = secrets.token_urlsafe(32)
    session = make_tracked_session(redact_values=(api_token, password))

    try:
        response = session.post(
            _webhooks_url(company_domain),
            json={
                "name": WEBHOOK_NAME,
                "subscription_url": webhook_url,
                "event_action": "*",
                "event_object": "*",
                "version": WEBHOOK_PAYLOAD_VERSION,
                "http_auth_user": WEBHOOK_AUTH_USER,
                "http_auth_password": password,
            },
            headers=_get_headers(api_token),
            timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except ValueError as e:
        return WebhookCreationResult(success=False, error=str(e))
    except HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        return WebhookCreationResult(success=False, error=_webhook_error_result("create", e, status_code))
    except RequestException as e:
        return WebhookCreationResult(success=False, error=_webhook_error_result("create", e, None))

    created_id = (response.json().get("data") or {}).get("id")
    _remove_superseded_webhooks(session, company_domain, api_token, webhook_url, created_id)

    return WebhookCreationResult(
        success=True,
        extra_inputs={"http_auth_user": WEBHOOK_AUTH_USER, "http_auth_password": password},
    )


def _remove_superseded_webhooks(
    session: Session, company_domain: str, api_token: str, webhook_url: str, created_id: Any
) -> None:
    """Drop earlier subscriptions on the same URL, best effort, after the replacement is live.

    Re-running setup mints a fresh password, so an older subscription would keep delivering with
    credentials the Hog function no longer accepts. Cleaning up after the create (rather than
    before) means the account is never left without a working webhook if the create fails.
    """
    try:
        for hook in _list_webhooks(company_domain, api_token):
            if hook.get("subscription_url") != webhook_url or hook.get("id") == created_id:
                continue
            session.delete(
                _webhooks_url(company_domain, hook.get("id")),
                headers=_get_headers(api_token),
                timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
            ).raise_for_status()
    except RequestException as e:
        LOGGER.warning("Could not remove superseded Pipedrive webhooks", error=str(e))


def get_external_webhook_info(company_domain: str, api_token: str, webhook_url: str) -> ExternalWebhookInfo:
    try:
        hooks = _list_webhooks(company_domain, api_token)
    except ValueError as e:
        return ExternalWebhookInfo(exists=False, error=str(e))
    except HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        return ExternalWebhookInfo(exists=False, error=_webhook_error_result("look up", e, status_code))
    except RequestException as e:
        return ExternalWebhookInfo(exists=False, error=_webhook_error_result("look up", e, None))

    matches = [hook for hook in hooks if hook.get("subscription_url") == webhook_url]
    if not matches:
        return ExternalWebhookInfo(exists=False, url=webhook_url)

    return ExternalWebhookInfo(
        exists=True,
        url=webhook_url,
        enabled_events=[f"{hook.get('event_action')}.{hook.get('event_object')}" for hook in matches],
        status="active" if any(hook.get("is_active") for hook in matches) else "inactive",
        created_at=matches[0].get("add_time"),
        description=matches[0].get("name"),
    )


def delete_webhook(company_domain: str, api_token: str, webhook_url: str) -> WebhookDeletionResult:
    try:
        hooks = _list_webhooks(company_domain, api_token)
    except ValueError as e:
        return WebhookDeletionResult(success=False, error=str(e))
    except HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        return WebhookDeletionResult(success=False, error=_webhook_error_result("delete", e, status_code))
    except RequestException as e:
        return WebhookDeletionResult(success=False, error=_webhook_error_result("delete", e, None))

    session = make_tracked_session(redact_values=(api_token,))
    for hook in hooks:
        if hook.get("subscription_url") != webhook_url:
            continue
        try:
            response = session.delete(
                _webhooks_url(company_domain, hook.get("id")),
                headers=_get_headers(api_token),
                timeout=WEBHOOK_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else None
            return WebhookDeletionResult(success=False, error=_webhook_error_result("delete", e, status_code))
        except RequestException as e:
            return WebhookDeletionResult(success=False, error=_webhook_error_result("delete", e, None))

    # Nothing matching left on the account, whether we deleted it now or it was already gone.
    return WebhookDeletionResult(success=True)


def pipedrive_source(
    company_domain: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
    webhook_source_manager: WebhookSourceManager,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = "v2",
) -> SourceResponse:
    config = endpoints_for_version(api_version)[endpoint]

    params: dict[str, Any] = {}
    if config.pagination == "cursor":
        # The cursor paginator only injects ``cursor``; ``limit`` must be a static param.
        params["limit"] = PAGE_SIZE

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(company_domain),
            # Only the non-secret Accept header here; the token travels via framework auth so it's
            # redacted from logged URLs, headers, sampled bodies, and raised error messages.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_token, "name": "x-api-token", "location": "header"},
            "paginator": _build_paginator(config),
            # base_url host (`{subdomain}.pipedrive.com`) is implicitly allowed; `[]` pins every
            # request — including resume URLs — to it, matching the source's SSRF posture.
            "allowed_hosts": [],
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Mirrors the old `data.get("data") or []`: a 200 body without `data` yields an
                    # empty page rather than raising (not required).
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        # Only new-shape paginator state can seed a resume; legacy `next_url`-only state restarts
        # the endpoint from the beginning (merge dedupes the re-yielded rows).
        if resume is not None and resume.paginator_state:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state:
            resumable_source_manager.save_state(PipedriveResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    webhook_enabled = async_to_sync(webhook_source_manager.webhook_enabled)()

    def items() -> Any:
        # Once the backfill has landed and the schema is on webhook sync, pushed rows replace the
        # poll for this run; the poll stays the only path until then.
        if webhook_enabled:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return resource

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
