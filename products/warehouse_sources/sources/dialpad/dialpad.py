import dataclasses
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from dateutil import parser

from products.warehouse_sources.sources.dialpad.settings import (
    CALL_TIMESTAMP_FIELDS,
    CALLS_LOOKBACK,
    DIALPAD_BASE_URL,
    DIALPAD_ENDPOINTS,
    SCORECARD_STATES,
    SCORECARD_TARGETS,
    SCORECARDS_PATH,
    DialpadEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    FanoutEndpointLike,
    JSONResponseCursorPaginator,
    Resource,
    RESTAPIConfig,
    RESTClient,
    ResumableSourceManager,
    SourceResponse,
    build_dependent_resource,
    create_auth,
    make_tracked_session,
    rest_api_resource,
)


@dataclasses.dataclass(frozen=True)
class DialpadResumeConfig:
    # The `cursor` that fetches the page after the last page the pipeline received.
    cursor: Optional[str] = None
    # The checkpoint of a fan-out endpoint: the parents that finished, and where the current one stands.
    fanout_state: Optional[dict[str, Any]] = None


def to_epoch_millis(value: Any) -> Optional[int]:
    """Convert an incremental watermark to the epoch milliseconds that `started_after` takes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day, tzinfo=UTC)
    elif isinstance(value, int | float):
        moment = datetime.fromtimestamp(value / 1000, tz=UTC)
    else:
        parsed = parser.parse(str(value))
        moment = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return int((moment - CALLS_LOOKBACK).timestamp() * 1000)


def _millis_to_datetime(value: Any) -> Any:
    # Dialpad can send int64 values as JSON strings, so a digit string counts as a number.
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    return value


def normalize_call(row: dict[str, Any]) -> dict[str, Any]:
    for key in CALL_TIMESTAMP_FIELDS:
        if row.get(key) is not None:
            row[key] = _millis_to_datetime(row[key])
    return row


def explode_call_labels(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"label": label} for label in body.get("labels") or []]


def explode_operators(parent_id_column: str) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """Turn one `{users, rooms}` operators response into one row per operator."""

    def explode(body: dict[str, Any]) -> list[dict[str, Any]]:
        parent = {parent_id_column: body.get(parent_id_column)}
        return [
            {**operator, "operator_type": operator_type, **parent}
            for key, operator_type in (("users", "user"), ("rooms", "room"))
            for operator in body.get(key) or []
        ]

    return explode


def _cursor_paginator() -> JSONResponseCursorPaginator:
    # A list page carries `cursor` in its body until the last page, which omits it.
    return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": DIALPAD_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "paginator": _cursor_paginator(),
    }


def get_resource(config: DialpadEndpointConfig, should_use_incremental_field: bool) -> EndpointResource:
    is_incremental = should_use_incremental_field and config.incremental_param is not None

    endpoint: Endpoint = {"path": config.path, "params": dict(config.params)}
    if config.paginated:
        endpoint["data_selector"] = "items"
    else:
        endpoint["paginator"] = "single_page"
    if is_incremental and config.incremental_param is not None:
        endpoint["incremental"] = {"start_param": config.incremental_param, "convert": to_epoch_millis}

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.name == "calls":
        resource["data_map"] = normalize_call
    elif config.name == "call_labels":
        resource["data_map"] = explode_call_labels
    return resource


def _fanout_source(
    api_key: str,
    config: DialpadEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DialpadResumeConfig],
) -> SourceResponse:
    fanout = config.fanout
    assert fanout is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(DialpadResumeConfig(fanout_state=state))

    child = build_dependent_resource(
        # The fan-out is always a full refresh with no page size param, so the helper reads no
        # page size or incremental default from these configs.
        endpoint_configs=cast(Mapping[str, FanoutEndpointLike], DIALPAD_ENDPOINTS),
        child_endpoint=config.name,
        fanout=fanout,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        page_size_param=None,
        parent_endpoint_extra={"data_selector": "items"},
        child_endpoint_extra={"data_selector": "items"} if config.paginated else {"paginator": "single_page"},
        resume_hook=save_checkpoint,
        initial_paginator_state=resume.fanout_state if resume is not None else None,
    )
    if not config.paginated:
        child = cast(Resource, child).add_map(explode_operators(fanout.parent_field_renames["id"]))

    return SourceResponse(
        name=config.name,
        items=lambda: child,
        primary_keys=config.primary_keys,
    )


def _scorecard_pages(
    api_key: str, resumable_source_manager: ResumableSourceManager[DialpadResumeConfig]
) -> Iterator[list[dict[str, Any]]]:
    client = RESTClient(base_url=DIALPAD_BASE_URL, auth=create_auth({"type": "bearer", "token": api_key}))
    for target_type, parent_name in SCORECARD_TARGETS:
        parent = DIALPAD_ENDPOINTS[parent_name]
        for target_page in client.paginate(
            path=parent.path, params=dict(parent.params), paginator=_cursor_paginator(), data_selector="items"
        ):
            for target in target_page:
                for state in SCORECARD_STATES:
                    for page in client.paginate(
                        path=SCORECARDS_PATH,
                        params={"target_type": target_type, "target_id": target["id"], "state": state},
                        paginator=_cursor_paginator(),
                        data_selector="items",
                    ):
                        if page:
                            yield [{**row, "target_type": target_type, "target_id": target["id"]} for row in page]
                        resumable_source_manager.safe_point()
            resumable_source_manager.safe_point()


def _scorecards_source(
    api_key: str, config: DialpadEndpointConfig, resumable_source_manager: ResumableSourceManager[DialpadResumeConfig]
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=lambda: _scorecard_pages(api_key, resumable_source_manager),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def dialpad_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DialpadResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = DIALPAD_ENDPOINTS[endpoint]
    if config.fanout is not None:
        return _fanout_source(api_key, config, team_id, job_id, resumable_source_manager)
    if config.path == SCORECARDS_PATH:
        return _scorecards_source(api_key, config, resumable_source_manager)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = {"cursor": resume.cursor} if resume is not None and resume.cursor else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None and state.get("cursor"):
            resumable_source_manager.save_state(DialpadResumeConfig(cursor=state["cursor"]))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(config, should_use_incremental_field)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # The call list is documented as newest first by start time, and takes no sort parameter.
        sort_mode="desc" if config.incremental_fields else None,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def get_status(api_key: str, path: str) -> Optional[int]:
    """GET one page of `path` and return the HTTP status, or `None` when the request failed."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{DIALPAD_BASE_URL}{path}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
