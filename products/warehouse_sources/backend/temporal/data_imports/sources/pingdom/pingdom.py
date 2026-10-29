import time
import dataclasses
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.pingdom.settings import (
    PINGDOM_ENDPOINTS,
    PingdomEndpointConfig,
)

PINGDOM_BASE_URL = "https://api.pingdom.com/api/3.1"


@dataclasses.dataclass
class PingdomResumeConfig:
    # Pingdom paginates with limit/offset; the static query params (limit,
    # incremental `from` filter) are deterministically rebuilt from the endpoint
    # config and job inputs on resume.
    offset: int = 0
    # Per-check tables checkpoint the shape `build_dependent_resource` emits, plus the window end
    # of the interrupted run, so checks finished before the interruption and the rest share one `to`.
    fanout_state: Optional[dict[str, Any]] = None
    window_end: Optional[int] = None


def _to_epoch(value: Any) -> Optional[int]:
    """Coerce an incremental cursor value to UNIX epoch seconds for Pingdom's `from` filter."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _paginator(config: PingdomEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    return OffsetPaginator(limit=config.page_size, total_path=None, maximum_offset=config.maximum_offset)


def _build_endpoint(config: PingdomEndpointConfig, should_use_incremental_field: bool) -> Endpoint:
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)

    params: dict[str, Any] = {}
    if is_incremental:
        cursor = config.incremental_fields[0]["field"]
        # Pingdom's `from` filter takes UNIX epoch seconds; only /actions exposes it.
        params["from"] = {
            "type": "incremental",
            "cursor_path": cursor,
            "initial_value": None,
            "convert": _to_epoch,
        }

    return {
        "path": config.path,
        "params": params,
        # Dotted selector (e.g. "actions.alerts") resolves the nested list; a 200 body that
        # lacks the key yields zero rows and stops (no data_selector_required — Pingdom's small
        # dimension endpoints legitimately return an empty/absent list).
        "data_selector": config.data_key,
        "paginator": _paginator(config),
    }


def _window_start_convert(
    config: PingdomEndpointConfig, window_start: Optional[int], window_end: int
) -> Callable[[Any], Optional[int]]:
    floor = window_end - config.max_window_seconds if config.max_window_seconds else None

    def convert(value: Any) -> Optional[int]:
        epoch = _to_epoch(value)
        if epoch is None:
            return window_start
        return max(epoch, floor) if floor is not None else epoch

    return convert


def _fanout_resource(
    config: PingdomEndpointConfig,
    fanout: DependentEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
) -> Iterable[Any]:
    parent_config = PINGDOM_ENDPOINTS[fanout.parent_name]

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    window_end = resume.window_end if resume and resume.window_end is not None else int(time.time())
    window_start = window_end - config.lookback_seconds if config.lookback_seconds else None

    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    child_params: dict[str, Any] = {**config.params, "to": window_end}
    if window_start is not None and not is_incremental:
        child_params["from"] = window_start

    def incremental_window(cursor_path: str) -> IncrementalConfig:
        return {
            "cursor_path": cursor_path,
            "start_param": "from",
            "convert": _window_start_convert(config, window_start, window_end),
        }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(PingdomResumeConfig(fanout_state=state, window_end=window_end))

    return build_dependent_resource(
        endpoint_configs=PINGDOM_ENDPOINTS,
        child_endpoint=config.name,
        fanout=fanout,
        client_config=client_config,
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=db_incremental_field_last_value if is_incremental else None,
        should_use_incremental_field=is_incremental,
        incremental_field=incremental_field,
        incremental_config_factory=incremental_window,
        parent_endpoint_extra={"data_selector": parent_config.data_key, "paginator": _paginator(parent_config)},
        child_endpoint_extra={"data_selector": config.data_key, "paginator": _paginator(config)},
        child_params_extra=child_params,
        page_size_param=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout_state if resume else None,
    )


def pingdom_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[PingdomResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = PINGDOM_ENDPOINTS[endpoint]

    client_config: ClientConfig = {
        "base_url": PINGDOM_BASE_URL,
        # Bearer auth via the framework so the token is redacted from logs and error messages.
        "auth": {"type": "bearer", "token": api_token},
    }

    resource: Iterable[Any]
    if config.fanout is not None:
        resource = _fanout_resource(
            config,
            config.fanout,
            client_config,
            team_id,
            job_id,
            resumable_source_manager,
            db_incremental_field_last_value,
            should_use_incremental_field,
            incremental_field,
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": _build_endpoint(config, should_use_incremental_field),
                }
            ],
        }

        initial_paginator_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume = resumable_source_manager.load_state()
            if resume is not None:
                initial_paginator_state = {"offset": resume.offset}

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
            # the last page (merge dedupes on primary key) rather than skipping it.
            if state and state.get("offset") is not None:
                resumable_source_manager.save_state(PingdomResumeConfig(offset=int(state["offset"])))

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
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Per-check rows arrive one check at a time, so they are not one ordered series.
        sort_mode=None if config.fanout else "asc",
    )


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap one-check listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{PINGDOM_BASE_URL}/checks?limit=1",
        headers={"Authorization": f"Bearer {api_token}"},
    )
    return ok
