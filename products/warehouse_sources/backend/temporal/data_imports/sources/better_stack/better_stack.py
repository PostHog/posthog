import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlsplit

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_BASE_URL,
    BETTER_STACK_ENDPOINTS,
    BetterStackEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

_TRUSTED_HOSTS = {"uptime.betterstack.com", "betterstack.com"}


class BetterStackUntrustedURLError(Exception):
    pass


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Better Stack API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `pagination.next` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/api/`
    path prefix keeps a poisoned resume state or a hostile upstream response from retargeting the
    request at another host and leaking the token (SSRF). Returns the URL unchanged when trusted.
    """
    parts = urlsplit(url)
    is_trusted = parts.scheme == "https" and parts.netloc in _TRUSTED_HOSTS and parts.path.startswith("/api/")
    if not is_trusted:
        raise BetterStackUntrustedURLError("Refusing to follow a pagination URL outside the Better Stack API")
    return url


class BetterStackPaginator(JSONResponsePaginator):
    """Follows the response's `pagination.next` URL, refusing any URL off a Better Stack origin —
    whether it arrived in a response body or was seeded from saved resume state.

    Unpaginated collections (roles, incident comments) and the single-object monitor endpoints
    carry no `pagination` key, so the first response is also the last."""

    def __init__(self) -> None:
        super().__init__(next_url_path="pagination.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)

    def set_resume_state(self, state: dict[str, Any]) -> None:
        super().set_resume_state(state)
        if self._next_url is not None:
            _validate_pagination_url(self._next_url)


@dataclasses.dataclass(frozen=True)
class BetterStackResumeConfig:
    # Full next-page URL from the response's `pagination.next` field (null on the last page). It
    # carries the page, per_page, and any `from` filter, so following it preserves the incremental
    # window on every page.
    next_url: str | None = None
    # Framework fan-out resume state for the parent-scoped endpoints, opaque to this source and
    # passed straight back to the fan-out helper:
    # {"completed": [child_path, ...], "current": child_path | None, "child_state": {...} | None}.
    fanout_state: dict[str, Any] | None = None


def _format_from_date(value: Any) -> str:
    """Format an incremental cursor value as the YYYY-MM-DD date the incidents `from` filter takes."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now — asking for incidents newer than now is a no-op,
    so clamping keeps the filter sane if a future-dated record ever pushes the cursor forward."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: BetterStackEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": config.page_size}

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        # The `from` filter is date-granular, so we re-fetch the watermark's whole day; merge on
        # the primary key dedupes the overlap.
        value = _clamp_future_value_to_now(db_incremental_field_last_value)
        params["from"] = _format_from_date(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


def _explode_response_times(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Explode a monitor's nested latency series into one row per region measurement.

    The response is a single object holding `regions[].response_times[]`, so flattening it the
    usual way would produce one row per monitor with the whole series buried in a list. `id` and
    `type` are dropped: `id` repeats the monitor id already carried by `monitor_id`, and naming a
    measurement row after its monitor would read as the row's own key.
    """
    attributes = item.get("attributes") or {}
    carried = {k: v for k, v in item.items() if k not in ("attributes", "id", "type")}
    rows: list[dict[str, Any]] = []
    for region in attributes.get("regions") or []:
        region_name = region.get("region")
        for measurement in region.get("response_times") or []:
            rows.append({**carried, "region": region_name, **measurement})
    return rows


def _no_request_window(_cursor_path: str) -> None:
    """Report that a fan-out child takes no server-side time filter.

    Neither child endpoint accepts one, so there is no cursor to bind a request window to. The
    child still merges on its primary key, which is what lets the parent listing bound the
    request set instead.
    """
    return None


def _client_config(api_token: str, base_url: str) -> ClientConfig:
    return {
        "base_url": base_url,
        # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
        "auth": {"type": "bearer", "token": api_token},
        # capture=False: incident `response_content` and monitor URLs can carry arbitrary
        # secrets the name-based scrubbers can't recognise, so keep them out of HTTP samples.
        "session": make_tracked_session(capture=False, redact_values=(api_token,)),
        "paginator": BetterStackPaginator(),
    }


def probe_credentials(api_token: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Better Stack collection. Returns the HTTP status code, or None on a
    connection failure. Probes the given endpoint's path when set, else the monitors collection."""
    config = BETTER_STACK_ENDPOINTS.get(endpoint) if endpoint else None
    if config is not None and config.fanout is not None:
        # A fan-out child's path is parent-scoped and has no collection of its own, so the
        # reachable thing to probe is the parent the child is enumerated from.
        config = BETTER_STACK_ENDPOINTS[config.fanout.parent_name]
    base_url = config.base_url if config else BETTER_STACK_BASE_URL
    path = config.path if config else "/v2/monitors"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(capture=False, redact_values=(api_token,)),
        f"{base_url}{path}?per_page=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return status


def _source_response(config: BetterStackEndpointConfig, items: Any) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Neither the incidents endpoint nor the fan-out children guarantee an ascending order —
        # incidents documents no sort param, and a fan-out walks parent by parent. Declaring
        # "desc" commits the incremental watermark once at the end of a successful sync, which is
        # safe for any arrival order, instead of checkpointing it per batch.
        sort_mode="desc" if config.incremental_fields else "asc",
    )


def _top_level_source(
    api_token: str,
    config: BetterStackEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token, config.base_url),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": _build_initial_params(
                        config, should_use_incremental_field, db_incremental_field_last_value
                    ),
                    # A missing `data` key is treated as an empty page (matching the API's
                    # envelope, which always carries `data`), so no data_selector_required here.
                    "data_selector": "data",
                },
                # Better Stack is JSON:API — hoist each item's `attributes` into the row root.
                "data_map": _flatten_item,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; the checkpoint lands AFTER a page is yielded so a
        # crash re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BetterStackResumeConfig(next_url=state["next_url"]))

    return _source_response(
        config,
        rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value if should_use_incremental_field else None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )


def _fanout_source(
    api_token: str,
    config: BetterStackEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    """Walk a parent collection, then fetch this endpoint once per parent row."""
    assert config.fanout is not None
    parent_config = BETTER_STACK_ENDPOINTS[config.fanout.parent_name]
    # The parent listing carries whatever server-side date filter it supports, floored by THIS
    # endpoint's watermark. For incident comments that means a sync only re-walks incidents that
    # started on or after the newest comment already collected: a comment posted later against an
    # older incident is picked up by a full refresh, not by the next incremental run. The
    # alternative — re-walking every incident ever recorded, one request each — costs more every
    # sync than the data it re-reads is worth.
    fanout = dataclasses.replace(
        config.fanout,
        parent_params={
            **_build_initial_params(parent_config, should_use_incremental_field, db_incremental_field_last_value),
            **config.fanout.parent_params,
        },
    )

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.fanout_state:
            initial_paginator_state = resume.fanout_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        resumable_source_manager.save_state(BetterStackResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=BETTER_STACK_ENDPOINTS,
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(api_token, config.base_url),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_config_factory=_no_request_window,
            # None of the child endpoints take a page-size param; the parent's rides in
            # `parent_params` above.
            page_size_param=None,
            parent_endpoint_extra={"paginator": BetterStackPaginator(), "data_selector": "data"},
            child_endpoint_extra={"paginator": BetterStackPaginator(), "data_selector": "data"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ),
    )
    # Added after the helper's own parent-field rename, so the renamed `monitor_id`/`incident_id`
    # is already on the row when these run.
    resource.add_map(_explode_response_times if config.name == "monitor_response_times" else _flatten_item)
    return _source_response(config, resource)


def better_stack_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BETTER_STACK_ENDPOINTS[endpoint]
    build = _fanout_source if config.fanout is not None else _top_level_source
    return build(
        api_token,
        config,
        team_id,
        job_id,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )
