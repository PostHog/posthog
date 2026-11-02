import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional, cast
from urllib.parse import urlencode, urlparse

from requests import Response

from posthog.cloud_utils import is_cloud

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_chained_resource,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.n8n.settings import (
    INSIGHTS_BACKFILL_DAYS,
    N8N_API_PATH,
    N8N_ENDPOINTS,
    N8nEndpointConfig,
)

INSIGHTS_REQUEST_TIMEOUT = 60
_ISO_UTC = "%Y-%m-%dT%H:%M:%S.000Z"


@dataclasses.dataclass(frozen=True)
class N8nResumeConfig:
    # The `nextCursor` token to fetch the next page. None means "start from the
    # first page" — used both on a fresh sync and when the bookmark predates any page.
    next_cursor: Optional[str] = None
    # Framework fan-out checkpoint ({"completed": [...], "current": ..., "child_state": ...}).
    fanout_state: Optional[dict[str, Any]] = None
    # Next UTC day (ISO date) the insights summary walk fetches.
    next_date: Optional[str] = None


def normalize_host(host: str) -> str:
    """Normalize the instance URL and reject anything that isn't plain http(s).

    Accepts either a bare host (`myinstance.app.n8n.cloud`) or a full URL, with or
    without the `/api/v1` suffix, and returns the instance origin (no trailing slash).
    """
    host = host.strip()
    if not host:
        raise ValueError("n8n host is required")
    if "://" not in host:
        host = f"https://{host}"
    host = host.rstrip("/")
    # Tolerate a pasted API base URL by trimming a trailing /api/v1.
    if host.endswith(N8N_API_PATH):
        host = host[: -len(N8N_API_PATH)]
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"Invalid n8n host: {host}")
    # The API key rides in the X-N8N-API-KEY header on every request, so plaintext http
    # would leak it to any network observer. On PostHog Cloud the request egresses over the
    # public internet, so require https. Self-hosted operators control their own network path
    # (e.g. an internal n8n reachable only over http), so http stays allowed there — mirroring
    # how host IP safety is only enforced on cloud.
    if parsed.scheme == "http" and is_cloud():
        raise ValueError("n8n instance URL must use https")
    # SSRF guard: urlparse treats a backslash as userinfo and an "@" as a userinfo
    # separator, but urllib3/requests treat the backslash as an authority separator, so
    # `http://127.0.0.1\@example.com` validates as example.com yet connects to 127.0.0.1.
    # A legitimate instance URL has no userinfo, so reject either construct outright.
    if "\\" in host or "%5c" in host.lower() or "@" in parsed.netloc:
        raise ValueError(f"Invalid n8n host: {host}")
    return host


def hostname_of(host: str) -> str:
    return urlparse(normalize_host(host)).hostname or ""


def _base_url(host: str) -> str:
    return f"{normalize_host(host)}{N8N_API_PATH}"


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-N8N-API-KEY": api_key, "Accept": "application/json"}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _client_config(host: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _base_url(host),
        # Auth (the X-N8N-API-KEY header) is supplied via the framework auth config so its
        # value is redacted from logs and raised errors; only the non-secret Accept header here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "X-N8N-API-KEY", "location": "header"},
        # n8n cursor pagination: `nextCursor` in the body, echoed back as the `cursor` query
        # param. A null/absent nextCursor terminates.
        "paginator": JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor"),
        # `host` is user-supplied, so pin redirects off so validation and the outbound request
        # stay on the same target (SSRF defense-in-depth).
        "allow_redirects": False,
    }


def _list_params(config: N8nEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)
    # The offset paginator sends its own `take`/`skip`, so only cursor endpoints take `limit`.
    if config.paginator == "cursor":
        params["limit"] = config.page_size
    return params


def _list_endpoint_extra(config: N8nEndpointConfig) -> Endpoint:
    paginator: BasePaginator
    if config.paginator == "offset":
        paginator = OffsetPaginator(limit=config.page_size, offset_param="skip", limit_param="take", total_path="count")
    else:
        paginator = JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor")
    return {
        "paginator": paginator,
        "data_selector": "data",
        # `data` is the required envelope field; a 200 body without it means the
        # response shape changed — fail loud instead of silently syncing 0 rows.
        "data_selector_required": True,
    }


def _list_endpoint(config: N8nEndpointConfig, params: dict[str, Any] | None = None) -> Endpoint:
    endpoint: Endpoint = {"path": config.path, "params": params if params is not None else _list_params(config)}
    endpoint.update(_list_endpoint_extra(config))
    return endpoint


def _chained_resource(config: N8nEndpointConfig, client_config: ClientConfig, team_id: int, job_id: str) -> Resource:
    """Build a grandparent -> parent -> child chain (workflows -> test runs -> test cases)."""
    fanout = config.fanout
    assert fanout is not None
    middle_config = N8N_ENDPOINTS[fanout.parent_name]
    root_fanout = middle_config.fanout
    assert root_fanout is not None
    root_config = N8N_ENDPOINTS[root_fanout.parent_name]

    root_resource: EndpointResource = {
        "name": root_config.name,
        "table_name": root_config.name,
        "write_disposition": "replace",
        "endpoint": _list_endpoint(root_config),
        "table_format": "delta",
    }
    middle_endpoint = _list_endpoint(
        middle_config,
        {
            **_list_params(middle_config),
            root_fanout.resolve_param: {
                "type": "resolve",
                "resource": root_config.name,
                "field": root_fanout.resolve_field,
            },
        },
    )
    middle_endpoint["response_actions"] = root_fanout.child_response_actions
    middle_resource: EndpointResource = {
        "name": middle_config.name,
        "table_name": middle_config.name,
        "write_disposition": "replace",
        # Carries the grandparent id onto each middle row so the child path can bind it.
        "include_from_parent": root_fanout.include_from_parent,
        "endpoint": middle_endpoint,
        "table_format": "delta",
    }
    child_endpoint = _list_endpoint(
        config,
        {
            **_list_params(config),
            root_fanout.resolve_param: {
                "type": "resolve",
                "resource": middle_config.name,
                "field": make_parent_key_name(root_config.name, root_fanout.resolve_field),
            },
            fanout.resolve_param: {"type": "resolve", "resource": middle_config.name, "field": fanout.resolve_field},
        },
    )
    child_endpoint["response_actions"] = fanout.child_response_actions
    child_resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "include_from_parent": fanout.include_from_parent,
        "endpoint": child_endpoint,
        "table_format": "delta",
    }

    return cast(
        Resource,
        build_chained_resource(
            resources=[root_resource, middle_resource, child_resource],
            child_name=config.name,
            parent_name=middle_config.name,
            parent_field_renames=fanout.parent_field_renames,
            client_config=client_config,
            team_id=team_id,
            job_id=job_id,
        ),
    )


def _insights_window(day: date) -> dict[str, str]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    return {"startDate": start.strftime(_ISO_UTC), "endDate": end.strftime(_ISO_UTC)}


def _insights_summary_rows(
    host: str,
    api_key: str,
    resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    """Yield one insights summary row per UTC day, oldest first, up to and including today."""
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    headers = _get_headers(api_key)
    url = f"{_base_url(host)}{N8N_ENDPOINTS['insights_summary'].path}"
    today = datetime.now(UTC).date()

    def fetch(day: date) -> Response:
        return session.get(_build_url(url, _insights_window(day)), headers=headers, timeout=INSIGHTS_REQUEST_TIMEOUT)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    last_value = parse_datetime_value(db_incremental_field_last_value)
    start: Optional[date] = None
    if resume is not None and resume.next_date is not None:
        start = date.fromisoformat(resume.next_date)
    elif last_value is not None:
        # Re-fetch the watermark day: it was still in progress when the last sync read it.
        start = last_value.date()

    backfill_starts = [today - timedelta(days=days) for days in INSIGHTS_BACKFILL_DAYS]
    candidates = backfill_starts if start is None else [start, *(d for d in backfill_starts if d > start)]

    day = candidates[0]
    response = fetch(day)
    for candidate in candidates[1:]:
        if response.status_code != 403:
            break
        resumable_source_manager.safe_point()
        day = candidate
        response = fetch(day)

    while True:
        # A 403 here means even the shortest window is refused, so the key lacks `insights:read`.
        response.raise_for_status()
        window = _insights_window(day)
        row = {"date": day.isoformat(), **window, **response.json()}
        next_day = day + timedelta(days=1)
        if next_day <= today:
            resumable_source_manager.save_state(N8nResumeConfig(next_date=next_day.isoformat()))
        yield [row]
        if next_day > today:
            return
        day = next_day
        response = fetch(day)


def n8n_source(
    host: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[N8nResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = N8N_ENDPOINTS[endpoint]

    if endpoint == "insights_summary":
        return _source_response(
            config,
            lambda: _insights_summary_rows(host, api_key, resumable_source_manager, db_incremental_field_last_value),
        )

    client_config = _client_config(host, api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None and N8N_ENDPOINTS[config.fanout.parent_name].fanout is not None:
        # A two-level chain carries no resume state; see build_chained_resource.
        chained = _chained_resource(config, client_config, team_id, job_id)
        return _source_response(config, lambda: chained, chained.column_hints)

    if config.fanout is not None:
        parent_config = N8N_ENDPOINTS[config.fanout.parent_name]

        def save_fanout_state(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(N8nResumeConfig(fanout_state=state))

        dependent = cast(
            Resource,
            build_dependent_resource(
                endpoint_configs=N8N_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=dataclasses.replace(config.fanout, parent_params=_list_params(parent_config)),
                client_config=client_config,
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=None,
                # Page size params differ per endpoint (`limit` vs `take`), so they go in the params below.
                page_size_param=None,
                parent_endpoint_extra=_list_endpoint_extra(parent_config),
                child_endpoint_extra=_list_endpoint_extra(config),
                child_params_extra=_list_params(config),
                resume_hook=save_fanout_state,
                initial_paginator_state=resume.fanout_state if resume is not None else None,
            ),
        )
        return _source_response(config, lambda: dependent, dependent.column_hints)

    rest_config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [{"name": endpoint, "endpoint": _list_endpoint(config)}],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resume is not None and resume.next_cursor is not None:
        initial_paginator_state = {"cursor": resume.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(N8nResumeConfig(next_cursor=state["cursor"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource, resource.column_hints)


def _source_response(
    config: N8nEndpointConfig,
    items: Callable[[], Iterable[Any]],
    column_hints: Optional[dict[str, Any]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=column_hints,
    )


def validate_credentials(host: str, api_key: str) -> bool:
    """Confirm the instance is reachable and the key is accepted.

    Probes /workflows with limit=1 — the most broadly-available scope on an API key.
    """
    try:
        url = _build_url(f"{_base_url(host)}/workflows", {"limit": 1})
    except ValueError:
        return False
    ok, _status = validate_via_probe(
        # `host` is user-supplied, so pin redirects off (SSRF defense-in-depth) and redact the key.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        url,
        headers=_get_headers(api_key),
        timeout=15,
    )
    return ok
