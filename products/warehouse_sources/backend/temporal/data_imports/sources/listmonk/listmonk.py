from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from requests.auth import HTTPBasicAuth

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.listmonk.settings import (
    ANALYTICS_BATCH_SIZE,
    ANALYTICS_FROM_DATE,
    ANALYTICS_TYPES,
    LISTMONK_API_PATH,
    LISTMONK_ENDPOINTS,
    PAGE_SIZE,
    ListmonkEndpointConfig,
)

REQUEST_TIMEOUT = 60


@frozen
class ListmonkResumeConfig:
    # Next page of a list endpoint.
    next_page: Optional[int] = None
    # Analytics position: the count type in progress, and the last campaign id it finished.
    analytics_type: Optional[str] = None
    analytics_after_id: Optional[int] = None


def normalize_host(host: str) -> str:
    """Return the instance origin (no trailing slash) from a bare host or a full URL.

    Rejects anything that is not plain http(s), and rejects http on PostHog Cloud because the
    API token would cross the public internet in clear text.
    """
    host = host.strip()
    if not host:
        raise ValueError("Listmonk instance URL is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    if host.endswith(LISTMONK_API_PATH):
        host = host[: -len(LISTMONK_API_PATH)]
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid Listmonk instance URL: {host}")
    if parsed.scheme == "http" and is_cloud():
        raise ValueError("Listmonk instance URL must use https")
    # urlparse reads a backslash and "@" as userinfo, while urllib3 reads the backslash as an
    # authority separator, so `http://127.0.0.1\@example.com` would validate one host and connect
    # to another. An instance URL has no userinfo, so reject both.
    if "\\" in host or "%5c" in host.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid Listmonk instance URL: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _api_base(host: str) -> str:
    return f"{normalize_host(host)}{LISTMONK_API_PATH}"


def updated_at_query(value: Any) -> str:
    # The watermark goes into a SQL expression, so only a parsed timestamp is ever formatted into it.
    parsed = parse_datetime_value(value)
    if parsed is None:
        raise ValueError(f"Cannot use {value!r} as a Listmonk updated_at filter")
    since = parsed.isoformat()
    # Opt-in confirmations and unsubscribes update `subscriber_lists` only, so match those too.
    return (
        f"(subscribers.updated_at >= '{since}' OR subscribers.id IN "
        f"(SELECT subscriber_id FROM subscriber_lists WHERE subscriber_lists.updated_at >= '{since}'))"
    )


def _client_config(host: str, api_user: str, api_token: str) -> ClientConfig:
    return {
        "base_url": _api_base(host),
        "headers": {"Accept": "application/json"},
        "auth": {"type": "http_basic", "username": api_user, "password": api_token},
        "paginator": PageNumberPaginator(base_page=1, page_param="page"),
        # The host is user supplied, so keep validation and the request on the same target.
        "allow_redirects": False,
    }


def get_resource(config: ListmonkEndpointConfig, is_incremental: bool) -> EndpointResource:
    params: dict[str, Any] = {"per_page": PAGE_SIZE, "order": "asc", **(config.extra_params or {})}
    if config.order_by is not None:
        params["order_by"] = config.order_by
    if is_incremental:
        params["query"] = {
            "type": "incremental",
            "cursor_path": "updated_at",
            "initial_value": "1970-01-01T00:00:00+00:00",
            "convert": updated_at_query,
        }
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {"path": config.path, "params": params, "data_selector": "data.results"},
        "table_format": "delta",
    }


def _campaign_ids(
    session: Any, base: str, auth: HTTPBasicAuth, manager: ResumableSourceManager[ListmonkResumeConfig]
) -> list[int]:
    ids: list[int] = []
    page = 1
    while True:
        response = session.get(
            f"{base}/campaigns",
            params={"page": page, "per_page": PAGE_SIZE, "order_by": "created_at", "order": "asc", "no_body": "true"},
            auth=auth,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        results = (response.json().get("data") or {}).get("results") or []
        if not results:
            return ids
        ids.extend(int(campaign["id"]) for campaign in results)
        # Listing ids yields no rows, so let the pipeline see a worker shutdown between pages.
        manager.safe_point()
        page += 1


def _campaign_analytics_rows(
    host: str,
    api_user: str,
    api_token: str,
    resumable_source_manager: ResumableSourceManager[ListmonkResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Yield daily view, click and bounce counts per campaign, one request per type and id batch."""
    session = make_tracked_session(redact_values=(api_token,), allow_redirects=False)
    auth = HTTPBasicAuth(api_user, api_token)
    base = _api_base(host)
    # Ids sort ascending so the resume position stays valid when a campaign is deleted between attempts.
    campaign_ids = sorted(_campaign_ids(session, base, auth, resumable_source_manager))
    to_date = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_type = resume.analytics_type if resume and resume.analytics_type in ANALYTICS_TYPES else ANALYTICS_TYPES[0]
    after_id = resume.analytics_after_id if resume and resume.analytics_after_id is not None else None

    for type_index in range(ANALYTICS_TYPES.index(start_type), len(ANALYTICS_TYPES)):
        analytics_type = ANALYTICS_TYPES[type_index]
        remaining = [campaign_id for campaign_id in campaign_ids if after_id is None or campaign_id > after_id]
        after_id = None
        for offset in range(0, len(remaining), ANALYTICS_BATCH_SIZE):
            batch = remaining[offset : offset + ANALYTICS_BATCH_SIZE]
            params: dict[str, Any] = {"id": batch, "from": ANALYTICS_FROM_DATE, "to": to_date}
            response = session.get(
                f"{base}{LISTMONK_ENDPOINTS['campaign_analytics'].path.format(type=analytics_type)}",
                params=params,
                auth=auth,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            counts = response.json().get("data") or []
            resumable_source_manager.save_state(
                ListmonkResumeConfig(analytics_type=analytics_type, analytics_after_id=batch[-1])
            )
            if counts:
                yield [{**count, "type": analytics_type} for count in counts]
            else:
                resumable_source_manager.safe_point()


def listmonk_source(
    host: str,
    api_user: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ListmonkResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = LISTMONK_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    def response(items: Any) -> SourceResponse:
        return SourceResponse(
            name=config.name,
            items=items,
            primary_keys=config.primary_keys,
            # Incremental rows arrive in id order, not `updated_at` order, so the watermark may only
            # move once the whole run has been read.
            sort_mode="desc" if is_incremental else "asc",
            partition_count=1 if config.partition_key else None,
            partition_size=1 if config.partition_key else None,
            partition_mode="datetime" if config.partition_key else None,
            partition_format="month" if config.partition_key else None,
            partition_keys=[config.partition_key] if config.partition_key else None,
        )

    if endpoint == "campaign_analytics":
        return response(lambda: _campaign_analytics_rows(host, api_user, api_token, resumable_source_manager))

    rest_config: RESTAPIConfig = {
        "client": _client_config(host, api_user, api_token),
        "resource_defaults": {},
        "resources": [get_resource(config, is_incremental)],
    }
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ListmonkResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state={"page": resume.next_page} if resume and resume.next_page is not None else None,
    )
    return response(lambda: resource)


def probe_credentials(host: str, api_user: str, api_token: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,), allow_redirects=False),
        f"{_api_base(host)}/lists?per_page=1",
        auth=HTTPBasicAuth(api_user, api_token),
        allow_redirects=False,
    )
