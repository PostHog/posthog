import dataclasses
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import (
    FRONT_ENDPOINTS,
    FrontEndpointConfig,
)

FRONT_BASE_URL = "https://api2.frontapp.com"
# Front cursors are absolute next-page links carried in ``_pagination.next``.
FRONT_NEXT_URL_PATH = "_pagination.next"
MAX_RETRIES = 6


@dataclasses.dataclass
class FrontResumeConfig:
    # Top-level endpoints resume from the absolute next-page link Front hands back.
    next_url: Optional[str] = None
    # Fan-out endpoints resume by parent: the child paths already fully synced, the parent in
    # progress, and that parent's paginator state — see
    # `common.rest_source.__init__._make_paginate_dependent_resource`.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def _accept_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so the token is redacted from logs;
    # only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _to_unix_seconds(value: Any) -> Any:
    """Coerce an incremental cursor value into Unix epoch seconds for Front's q[after] filter.

    Front stores timestamps as Unix epoch seconds; the warehouse may hand the value back as a
    datetime/date or as the raw numeric column, so normalize both into something serializable as
    a number.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp()
    return value


def _resolve_after_value(
    config: FrontEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Any:
    if not should_use_incremental_field:
        return None
    if db_incremental_field_last_value is not None:
        return _to_unix_seconds(db_incremental_field_last_value)
    if config.default_lookback_days is not None:
        return (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).timestamp()
    return None


def _build_initial_params(
    config: FrontEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.limit is not None:
        params["limit"] = config.limit
    if config.sort_by is not None:
        params["sort_by"] = config.sort_by
    if config.sort_order is not None:
        params["sort_order"] = config.sort_order

    if config.supports_incremental and config.incremental_query_property:
        after_value = _resolve_after_value(config, should_use_incremental_field, db_incremental_field_last_value)
        if after_value is not None:
            params[f"q[{config.incremental_query_property}]"] = after_value

    return params


def validate_credentials(api_token: str, path: str, require_scope: bool) -> tuple[bool, str | None]:
    """Probe a Front endpoint with the token.

    401 always fails (bad token). 403 means the token is valid but lacks scope for that endpoint:
    we accept it at source-create (``require_scope=False``) and only reject it when validating a
    specific schema (``require_scope=True``). Any other response (200, 404, ...) means the token
    is genuine.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{FRONT_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {api_token}", **_accept_headers()},
    )

    if status is None:
        return False, "Could not connect to Front. Please try again."
    if status == 401:
        return False, "Invalid Front API token. Please reconnect with a valid token."
    if status == 403 and require_scope:
        return False, "Your Front API token does not have permission to access this resource."
    return True, None


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": FRONT_BASE_URL,
        "headers": _accept_headers(),
        "auth": {"type": "bearer", "token": api_token},
        "max_retries": MAX_RETRIES,
    }


def _endpoint_extra() -> Endpoint:
    # Front pages carry rows under ``_results``; a missing key is a legit empty page
    # (deleted resources can shrink a page), so this is not data_selector_required.
    return {
        "data_selector": "_results",
        "paginator": JSONResponsePaginator(next_url_path=FRONT_NEXT_URL_PATH),
    }


def _source_response(config: FrontEndpointConfig, items: Any, column_hints: Any = None) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        column_hints=column_hints,
    )


def _fanout_source(
    config: FrontEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FrontResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = FRONT_ENDPOINTS[config.fanout.parent_name]
    # Both listings already describe their own query params, so carry those through and let the
    # builder add none of its own.
    fanout = dataclasses.replace(
        config.fanout,
        parent_params=_build_initial_params(parent_config, False, None),
        child_params=_build_initial_params(config, False, None),
    )

    initial_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and (resume.completed or resume.current):
            initial_state = {
                "completed": resume.completed or [],
                "current": resume.current,
                "child_state": resume.child_state,
            }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                FrontResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    dependent_resource = cast(
        Iterable[Any],
        build_dependent_resource(
            endpoint_configs=FRONT_ENDPOINTS,
            child_endpoint=config.name,
            fanout=fanout,
            client_config=_client_config(api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_endpoint_extra(),
            child_endpoint_extra=_endpoint_extra(),
            page_size_param=None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )

    return _source_response(config, lambda: dependent_resource)


def front_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FrontResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FRONT_ENDPOINTS[endpoint]

    if config.fanout is not None:
        return _fanout_source(config, api_token, team_id, job_id, resumable_source_manager)

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {**_endpoint_extra(), "path": config.path, "params": params},
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_url:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FrontResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return _source_response(config, lambda: resource, column_hints=resource.column_hints)
