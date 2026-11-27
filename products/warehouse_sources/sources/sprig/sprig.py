import dataclasses
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urljoin, urlparse

import requests

from products.warehouse_sources.sources.sdk import (
    AuthConfig,
    ClientConfig,
    EndpointResource,
    FanoutEndpointLike,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    make_tracked_session,
    rest_api_resource,
)
from products.warehouse_sources.sources.sprig.settings import SPRIG_API_BASE_URL, SPRIG_ENDPOINTS, SprigApi


@dataclasses.dataclass(frozen=False)
class SprigResumeConfig:
    next_cursor: str


class SprigRedirectError(Exception):
    """The API answered with a 3xx. Redirects are refused so the API key stays on the API host."""


def _refuse_redirect(response: requests.Response) -> None:
    if not 300 <= response.status_code < 400:
        return
    location = response.headers.get("Location") or ""
    target = urlparse(urljoin(response.url or "", location)).hostname or "an unknown host"
    raise SprigRedirectError(f"Sprig redirected the API request to {target}; refusing to follow")


def _format_incremental_value(value: Any) -> Optional[int]:
    """Format an incremental cursor value as milliseconds since epoch for Sprig's `start` filter.

    The incremental field is always a datetime, but `date`/numeric/string values are handled
    defensively. `None` (initial sync, no watermark yet) returns `None` so the REST client drops
    the param and the first sync walks the full history.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(utc_dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value)).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def _incremental_param_config(incremental_field: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": incremental_field,
        "initial_value": None,
        "convert": _format_incremental_value,
    }


def get_resource(name: str, should_use_incremental_field: bool) -> EndpointResource:
    cfg = SPRIG_ENDPOINTS[name]
    incremental = should_use_incremental_field and cfg.supports_incremental

    params: dict[str, Any] = {}
    if cfg.page_size is not None:
        params["limit"] = cfg.page_size
    if incremental:
        params["start"] = _incremental_param_config("createdAt")

    return {
        "name": cfg.name,
        "table_name": cfg.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": {
            "data_selector": "data",
            "path": cfg.path,
            "params": params,
        },
        "table_format": "delta",
    }


def _auth(api: SprigApi, api_key: str) -> AuthConfig:
    if api == "study_v2":
        return {"type": "api_key", "name": "Authorization", "api_key": f"API-Key {api_key}", "location": "header"}
    return {"type": "bearer", "token": api_key}


def _client_config(api: SprigApi, api_key: str) -> ClientConfig:
    return {
        "base_url": SPRIG_API_BASE_URL,
        "auth": _auth(api, api_key),
        # Sprig returns `{"data": [...], "cursor": "<base64>"|null}` — the same field name
        # both as the response's next-page pointer and the request's pagination param.
        "paginator": JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor"),
        # A redirect must not carry the API key to another host; the REST client rejects
        # any 3xx when redirects are off.
        "allow_redirects": False,
    }


def _source_response(endpoint: str, items: Iterable[Any], column_hints: Optional[Any] = None) -> SourceResponse:
    cfg = SPRIG_ENDPOINTS[endpoint]
    return SourceResponse(
        name=cfg.name,
        items=lambda: items,
        primary_keys=cfg.primary_keys,
        column_hints=column_hints,
        # The v1 export endpoints take no `sort` param and document no default order. The
        # `start`/`end` window is documented as a created-since filter meant to be advanced
        # forward for incremental sync, so ascending creation order is assumed there. Verify
        # against a live account before relying on this in production — if the API actually
        # returns newest-first, this must switch to sort_mode="desc" (see orb/orb.py) or the
        # incremental watermark will skip data.
        sort_mode=cfg.sort_mode,
        partition_count=1 if cfg.partition_key else None,
        partition_size=1 if cfg.partition_key else None,
        partition_mode="datetime" if cfg.partition_key else None,
        partition_format="week" if cfg.partition_key else None,
        partition_keys=[cfg.partition_key] if cfg.partition_key else None,
    )


def sprig_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SprigResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    cfg = SPRIG_ENDPOINTS[endpoint]
    client_config = _client_config(cfg.api, api_key)

    if cfg.fanout is not None:
        # No resume hook: the per-parent resume state lists every completed Study and is rewritten
        # after each child page, so it grows with the number of Studies.
        child = build_dependent_resource(
            endpoint_configs=cast(Mapping[str, FanoutEndpointLike], SPRIG_ENDPOINTS),
            child_endpoint=endpoint,
            fanout=cfg.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra={"data_selector": "data"},
            child_endpoint_extra={"data_selector": "data"},
        )
        return _source_response(endpoint, child)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": None,
        "resources": [get_resource(endpoint, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.next_cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saving after each yielded batch means a crash re-yields the last page
        # (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(SprigResumeConfig(next_cursor=str(state["cursor"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(endpoint, resource, resource.column_hints)


def validate_credentials(api_key: str) -> bool:
    """Cheap probe against `/v1/surveys` to confirm the Bearer token is genuine.

    Returns False only for auth failures (401/403). Transient or unexpected statuses (429,
    5xx, ...) are raised via `raise_for_status()` so they surface as a real error rather than
    being misreported to the user as an invalid API key. A 3xx is refused before that check,
    because `raise_for_status()` treats it as success.
    """
    response = make_tracked_session(allow_redirects=False).get(
        f"{SPRIG_API_BASE_URL}/v1/surveys",
        params={"limit": 1},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    if response.status_code in (401, 403):
        return False
    _refuse_redirect(response)
    response.raise_for_status()
    return True
