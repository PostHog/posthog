import secrets
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit

import orjson
import pyarrow as pa
from asgiref.sync import async_to_sync
from requests import Session

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import table_from_py_list
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_ENDPOINTS,
    CALENDLY_WEBHOOK_EVENTS,
    WEBHOOK_SCHEMA_NAMES,
    CalendlyEndpointConfig,
)
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
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

CALENDLY_BASE_URL = "https://api.calendly.com"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60

# Calendly webhook subscriptions are scoped to an organization or a single user. Every table this
# source syncs is read with the `organization` scope param, so the subscription matches it.
CALENDLY_WEBHOOK_SCOPE = "organization"

CALENDLY_API_VERSION_V1 = "v1"
CALENDLY_API_VERSION_V2 = "v2"
SUPPORTED_API_VERSIONS = (CALENDLY_API_VERSION_V1, CALENDLY_API_VERSION_V2)

# Both declared versions target Calendly's current REST API host. The original "v1" label
# already pointed here, so v2 resolves byte-for-byte identically while becoming the default
# for new sources; a future breaking version would branch its host/paths from here.
_BASE_URL_BY_VERSION: dict[str, str] = {
    CALENDLY_API_VERSION_V1: CALENDLY_BASE_URL,
    CALENDLY_API_VERSION_V2: CALENDLY_BASE_URL,
}


def _base_url_for_version(api_version: str) -> str:
    return _BASE_URL_BY_VERSION.get(api_version, CALENDLY_BASE_URL)


@dataclasses.dataclass
class CalendlyResumeConfig:
    next_url: str


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC string, which Calendly's time filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def validate_credentials(token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(token,)),
        f"{CALENDLY_BASE_URL}/users/me",
        headers=_get_headers(token),
    )
    return ok


def get_current_organization(token: str, base_url: str = CALENDLY_BASE_URL) -> str:
    """Resolve the organization URI for the token via `/users/me`.

    Every list endpoint we sync is scoped by this URI, so we access it directly and let a
    malformed response surface immediately as a KeyError rather than degrading to None.
    """
    response = make_tracked_session(redact_values=(token,)).get(
        f"{base_url}/users/me", headers=_get_headers(token), timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["resource"]["current_organization"]


def _build_initial_params(
    config: CalendlyEndpointConfig,
    organization: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"count": PAGE_SIZE}

    if config.scope_param and organization:
        params[config.scope_param] = organization

    if config.sort:
        params["sort"] = config.sort

    if config.incremental_filter_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def calendly_source(
    token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalendlyResumeConfig],
    api_version: str = CALENDLY_API_VERSION_V1,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    webhook_source_manager: Optional[WebhookSourceManager] = None,
) -> SourceResponse:
    config = CALENDLY_ENDPOINTS[endpoint]
    base_url = _base_url_for_version(api_version)

    def get_rows() -> Iterator[Any]:
        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        initial_paginator_state: Optional[dict[str, Any]] = None
        organization: str | None = None
        if resume_config is not None:
            # The saved next-page URL is self-contained, so the `/users/me` bootstrap is skipped.
            initial_paginator_state = {"next_url": resume_config.next_url}
        elif config.scope_param == "organization":
            organization = get_current_organization(token, base_url)

        params = _build_initial_params(
            config, organization, should_use_incremental_field, db_incremental_field_last_value
        )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": base_url,
                "headers": {"Content-Type": "application/json"},
                "auth": {"type": "bearer", "token": token},
                "paginator": JSONResponsePaginator(next_url_path="pagination.next_page"),
            },
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": params,
                        # A missing `collection` key is treated as an empty page (matching the API's
                        # tolerant contract); pagination keeps following `next_page` until it's null,
                        # even across empty pages.
                        "data_selector": "collection",
                    },
                }
            ],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; saved AFTER a page is yielded so a crash
            # re-yields the last page (merge dedupes on `uri`) rather than skipping it.
            if state and state.get("next_url"):
                resumable_source_manager.save_state(CalendlyResumeConfig(next_url=state["next_url"]))

        yield from rest_api_resource(
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

    def items() -> Any:
        if webhook_enabled and webhook_source_manager is not None:
            return webhook_source_manager.get_items(table_transformer=_webhook_table_transformer)
        return get_rows()

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=["uri"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Coerce a Calendly RFC 3339 timestamp to an aware UTC datetime, or None when unusable."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _maybe_json(value: Any) -> Any:
    """The buffering layer may hand nested structures back as JSON strings."""
    if isinstance(value, str | bytes):
        try:
            return orjson.loads(value)
        except orjson.JSONDecodeError:
            return None
    return value


def _webhook_table_transformer(table: pa.Table) -> pa.Table:
    """Reshape Calendly invitee deliveries into rows matching the polled `scheduled_events` table.

    A delivery is the envelope `{"event", "created_at", "created_by", "payload": {<invitee>}}`, and
    the invitee embeds the whole scheduled event under `payload.scheduled_event` using the same
    field names `GET /scheduled_events` returns. We lift that object out and keep only the newest
    version per `uri` in the batch: delta merge dedupes across syncs, so a batch carrying
    `invitee.created` then `invitee.canceled` for one meeting must collapse to the latest row here.
    """
    if "payload" not in table.column_names:
        return table_from_py_list([])

    payloads = table.column("payload").to_pylist()
    if "created_at" in table.column_names:
        event_times = table.column("created_at").to_pylist()
    else:
        event_times = [None] * len(payloads)

    latest_by_uri: dict[Any, tuple[Optional[datetime], dict[str, Any]]] = {}
    for payload, event_time in zip(payloads, event_times):
        payload = _maybe_json(payload)
        if not isinstance(payload, dict):
            continue
        scheduled_event = _maybe_json(payload.get("scheduled_event"))
        if not isinstance(scheduled_event, dict) or scheduled_event.get("uri") is None:
            continue

        # The envelope timestamp is when Calendly emitted the event, which orders two deliveries
        # for one meeting even when the nested object's own `updated_at` is stale or absent.
        occurred_at = _parse_datetime(event_time) or _parse_datetime(scheduled_event.get("updated_at"))
        existing = latest_by_uri.get(scheduled_event["uri"])
        # Later rows win ties so batch arrival order breaks equal or missing timestamps.
        if existing is None or existing[0] is None or (occurred_at is not None and occurred_at >= existing[0]):
            latest_by_uri[scheduled_event["uri"]] = (occurred_at, scheduled_event)

    return table_from_py_list([row for _, row in latest_by_uri.values()])


class CalendlyUntrustedURLError(Exception):
    pass


def _assert_calendly_origin(url: str, base_url: str) -> None:
    """Reject a paginated webhook-management URL that points off the Calendly API origin.

    `pagination.next_page` is response-controlled and the webhook-management session sends the
    access token on every request, so a poisoned next link (off-host, downgraded to http, or on a
    non-default port, which netloc carries) would otherwise exfiltrate the token. Redirects are
    separately refused by the no-redirect session `_webhook_session` builds.
    """
    split = urlsplit(url)
    if not (split.scheme == "https" and split.netloc == urlsplit(base_url).netloc):
        raise CalendlyUntrustedURLError(f"Refusing to follow a Calendly URL outside {base_url}")


def _webhook_session(token: str) -> Session:
    return make_tracked_session(
        headers=_get_headers(token),
        redact_values=(token,),
        # Subscription responses carry the signing key, so keep the raw bodies out of HTTP sample
        # capture even when an operator enables it; no-redirect pins the credentialed request to
        # the origin it validated.
        capture=False,
        allow_redirects=False,
    )


def _list_webhook_subscriptions(session: Session, base_url: str, organization: str) -> Iterator[dict[str, Any]]:
    query = urlencode({"organization": organization, "scope": CALENDLY_WEBHOOK_SCOPE, "count": PAGE_SIZE})
    next_url: Optional[str] = f"{base_url}/webhook_subscriptions?{query}"
    while next_url:
        _assert_calendly_origin(next_url, base_url)
        response = session.get(next_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        body = response.json()
        yield from (item for item in body.get("collection") or [] if isinstance(item, dict))
        next_url = (body.get("pagination") or {}).get("next_page")


def _subscriptions_matching(session: Session, base_url: str, organization: str, webhook_url: str) -> list[dict]:
    return [
        item
        for item in _list_webhook_subscriptions(session, base_url, organization)
        if item.get("callback_url") == webhook_url
    ]


def _subscription_uuid(subscription: dict[str, Any]) -> Optional[str]:
    """Take the trailing id off a subscription URI so we build the delete URL ourselves.

    The response-supplied `uri` never becomes a request target; only this opaque segment does.
    """
    uri = subscription.get("uri")
    if not isinstance(uri, str):
        return None
    segment = uri.rstrip("/").rsplit("/", 1)[-1]
    return segment or None


def _delete_subscriptions(session: Session, base_url: str, subscriptions: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for subscription in subscriptions:
        uuid = _subscription_uuid(subscription)
        if uuid is None:
            errors.append(f"subscription {subscription.get('uri')}: could not read its id")
            continue
        response = session.delete(f"{base_url}/webhook_subscriptions/{quote(uuid, safe='')}", timeout=REQUEST_TIMEOUT)
        if response.status_code not in (200, 204):
            errors.append(f"subscription {uuid}: HTTP {response.status_code}")
    return errors


def create_webhook(token: str, webhook_url: str, api_version: str = CALENDLY_API_VERSION_V2) -> WebhookCreationResult:
    """Register an organization-scoped webhook subscription pointing at `webhook_url`.

    We generate the signing key rather than letting Calendly pick one, and drop any subscription
    already pointing at this URL first: Calendly rejects a duplicate callback URL and never returns
    an existing subscription's signing key, so recreating is the only way to end up holding a key
    we can verify deliveries with.
    """
    base_url = _base_url_for_version(api_version)
    signing_key = secrets.token_hex(32)

    try:
        session = _webhook_session(token)
        organization = get_current_organization(token, base_url)

        _delete_subscriptions(session, base_url, _subscriptions_matching(session, base_url, organization, webhook_url))

        response = session.post(
            f"{base_url}/webhook_subscriptions",
            json={
                "url": webhook_url,
                "events": list(CALENDLY_WEBHOOK_EVENTS),
                "organization": organization,
                "scope": CALENDLY_WEBHOOK_SCOPE,
                "signing_key": signing_key,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in (200, 201):
            detail = "Webhooks need a Standard plan or higher, and organization-wide subscriptions need an admin or owner token."
            return WebhookCreationResult(
                success=False,
                error=(
                    f"Calendly rejected the webhook subscription (HTTP {response.status_code}). {detail} "
                    "Please create it manually below."
                ),
            )

        # Calendly echoes the key back; prefer its value so a server-side rewrite can't leave us
        # verifying against a key it never stored.
        returned = ((response.json() or {}).get("resource") or {}).get("signing_key")
        return WebhookCreationResult(success=True, extra_inputs={"signing_secret": returned or signing_key})
    except Exception as e:
        return WebhookCreationResult(
            success=False,
            error=f"Failed to create the Calendly webhook subscription: {e}. Please create it manually below.",
        )


def get_external_webhook_info(
    token: str, webhook_url: str, api_version: str = CALENDLY_API_VERSION_V2
) -> ExternalWebhookInfo:
    base_url = _base_url_for_version(api_version)
    try:
        session = _webhook_session(token)
        organization = get_current_organization(token, base_url)
        matching = _subscriptions_matching(session, base_url, organization, webhook_url)
        if not matching:
            return ExternalWebhookInfo(exists=False)

        subscription = matching[0]
        return ExternalWebhookInfo(
            exists=True,
            url=subscription.get("callback_url"),
            enabled_events=subscription.get("events"),
            status=subscription.get("state"),
            created_at=subscription.get("created_at"),
        )
    except Exception as e:
        return ExternalWebhookInfo(exists=False, error=str(e))


def delete_webhook(token: str, webhook_url: str, api_version: str = CALENDLY_API_VERSION_V2) -> WebhookDeletionResult:
    base_url = _base_url_for_version(api_version)
    try:
        session = _webhook_session(token)
        organization = get_current_organization(token, base_url)
        errors = _delete_subscriptions(
            session, base_url, _subscriptions_matching(session, base_url, organization, webhook_url)
        )
        if errors:
            return WebhookDeletionResult(success=False, error="; ".join(errors))
        return WebhookDeletionResult(success=True)
    except Exception as e:
        return WebhookDeletionResult(success=False, error=str(e))
