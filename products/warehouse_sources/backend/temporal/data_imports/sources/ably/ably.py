import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import quote

from requests.exceptions import RequestException

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.settings import (
    ABLY_ENDPOINTS,
    BASE_URL,
    AblyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Ably REST protocol version, sent via the `X-Ably-Version` header. The legacy label
# (`UNVERSIONED_API_VERSION`, "v1") predates this source declaring a version and maps to *no*
# header — the exact request the source has always made, which Ably serves under its current
# default. Ably protocol 1 was sunset on 2025-11-01, so sending an explicit `X-Ably-Version: 1`
# would only start failing otherwise-working syncs; the deprecation banner and repin migration
# move those rows to "2" instead. The "2" pin sends the header so the source stays on protocol 2
# rather than silently tracking whatever Ably later makes its default.
ABLY_VERSION_2 = "2"

_VERSION_HEADER: dict[str, str] = {
    ABLY_VERSION_2: ABLY_VERSION_2,
}


def version_header(api_version: str) -> dict[str, str]:
    """`X-Ably-Version` header for a resolved version pin. Versions absent from the map (the
    legacy unversioned label) send no header — see the note on `_VERSION_HEADER`."""
    value = _VERSION_HEADER.get(api_version)
    return {"X-Ably-Version": value} if value else {}


@frozen
class AblyResumeConfig:
    # `/stats` and `/channels` are flat listings, so their resume state is the next page URL.
    next_url: Optional[str] = None
    # Channel-scoped endpoints fan out over `/channels`, whose resume state is the shape
    # `build_dependent_resource` checkpoints: which parents finished and where the current one
    # stopped.
    fanout_state: Optional[dict[str, Any]] = None


def split_api_key(api_key: str) -> tuple[str, str]:
    """Ably app API keys are `{app-id}.{key-id}:{key-secret}` — Basic auth splits on the
    first colon (https://ably.com/docs/api/rest-api#authentication)."""
    username, _, password = api_key.partition(":")
    return username, password


def _add_interval_start(row: dict[str, Any]) -> dict[str, Any]:
    """Ably's `intervalId` is a granularity-dependent string, e.g. `2024-01-15:14:05` for
    `unit=minute`, `2024-01-15:14` for `unit=hour`/`day`/`month`. Derive real columns from it:
    `interval_start` (ISO datetime, for partitioning/display) and `interval_start_ms` (Unix ms,
    the same unit Ably's `start`/`end` stats params use — so it doubles as the incremental
    cursor fed straight back into the next sync's `start` param, no reformatting needed)."""
    parsed = _parse_interval_start(row.get("intervalId"))
    row["interval_start"] = parsed.isoformat() if parsed else None
    row["interval_start_ms"] = int(parsed.timestamp() * 1000) if parsed else None
    return row


def _parse_interval_start(interval_id: Optional[str]) -> Optional[datetime]:
    if not interval_id:
        return None

    parts = interval_id.split(":")
    date_part = parts[0]

    try:
        year, month, day = (int(component) for component in date_part.split("-"))
        hour = int(parts[1]) if len(parts) > 1 else 0
        minute = int(parts[2]) if len(parts) > 2 else 0
        return datetime(year, month, day, hour, minute, tzinfo=UTC)
    except (ValueError, IndexError):
        # Unexpected intervalId shape — leave the incremental/partition columns unset rather
        # than raising, so a single malformed bucket doesn't fail the whole sync.
        return None


def _add_channel_path(row: dict[str, Any]) -> dict[str, Any]:
    """Derive the path segment the channel-scoped endpoints are addressed by.

    Ably channel names commonly carry separators (`chat:room1`, `user/42/inbox`), and the
    fan-out substitutes the value into `/channels/{channel_id}/...` with `str.format`, which
    escapes nothing. An unencoded `/` would address a different path, so encode every reserved
    character here.
    """
    channel_id = row.get("channelId")
    if isinstance(channel_id, str):
        row["channel_path"] = quote(channel_id, safe="")
    return row


def _add_message_time(row: dict[str, Any]) -> dict[str, Any]:
    """Derive an ISO datetime from the Unix ms `timestamp`, because partitioning wants an actual
    datetime-typed column. The raw `timestamp` stays as the incremental cursor, since that is the
    unit Ably's `start`/`end` history params take."""
    timestamp = row.get("timestamp")
    row["message_time"] = (
        datetime.fromtimestamp(timestamp / 1000, tz=UTC).isoformat() if isinstance(timestamp, int) else None
    )
    return row


# Applied per row on the fan-out children, which build their resource through the shared helper
# and so cannot carry a resource-level `data_map` of their own.
_CHILD_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "ChannelMessages": _add_message_time,
}


def _map_pages(
    pages: Iterable[list[dict[str, Any]]], mapper: Callable[[dict[str, Any]], dict[str, Any]]
) -> Iterator[list[dict[str, Any]]]:
    for page in pages:
        yield [mapper(row) for row in page]


def _incremental_window(cursor_path: str) -> IncrementalConfig:
    """Both incremental endpoints take a Unix-ms `start`/`end` pair and count from the epoch.

    Ably has no open-ended "everything since X" mode, so every request needs an explicit end.
    Bind it to "now" at request-build time (this function runs fresh each sync) rather than
    relying on the vendor's own end-of-window default.
    """
    return {
        "cursor_path": cursor_path,
        "start_param": "start",
        "end_param": "end",
        "initial_value": "0",
        "end_value": str(int(time.time() * 1000)),
    }


def _client_config(api_key: str, api_version: str) -> ClientConfig:
    username, password = split_api_key(api_key)
    return {
        "base_url": BASE_URL,
        "headers": version_header(api_version),
        "auth": {
            "type": "http_basic",
            "username": username,
            "password": password,
        },
        # Pin every request to BASE_URL's host and refuse redirects: the Basic auth header
        # carries the Ably key, so a spoofed `Link: rel="next"` target or a cross-origin 3xx
        # must not carry that credential off-host (SSRF). `allowed_hosts=[]` means "same host
        # as base_url only" and also pins paginator and resume URLs.
        "allowed_hosts": [],
        "allow_redirects": False,
        "paginator": "header_link",
    }


# Applied as a resource-level `data_map` on the top-level endpoints that derive columns.
_TOP_LEVEL_ROW_MAPS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "Stats": _add_interval_start,
}


def get_resource(
    endpoint: str,
    unit: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str] = None,
) -> EndpointResource:
    """Builds a top-level (non-fan-out) resource. Channel-scoped endpoints fan out from
    `Channels` and are built via `build_dependent_resource` in `ably_source`."""
    config = ABLY_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": config.page_size, **config.params}
    if endpoint == "Stats":
        params["unit"] = unit

    endpoint_config: Endpoint = {
        "path": config.path,
        "paginator": "header_link",
        "params": params,
        "data_selector_required": True,
    }

    use_merge = should_use_incremental_field and bool(config.incremental_fields)
    if use_merge:
        endpoint_config["incremental"] = _incremental_window(
            incremental_field or config.default_incremental_field or "id"
        )

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_merge else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    row_map = _TOP_LEVEL_ROW_MAPS.get(endpoint)
    if row_map is not None:
        resource["data_map"] = row_map
    return resource


def _make_source_response(
    config: AblyEndpointConfig,
    items: Callable[[], Iterable[Any]],
    column_hints: Optional[dict[str, Any]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_key,
        column_hints=column_hints,
        partition_mode="datetime" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def ably_source(
    api_key: str,
    endpoint: str,
    unit: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AblyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    api_version: str,
    should_use_incremental_field: bool = False,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    endpoint_config = ABLY_ENDPOINTS.get(endpoint)
    if endpoint_config is None:
        raise ValueError(f"Unknown Ably endpoint: {endpoint}")

    client_config = _client_config(api_key, api_version)
    resume_state = _load_resume_state(resumable_source_manager)

    if endpoint_config.fanout is not None:
        child = build_dependent_resource(
            endpoint_configs=ABLY_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=client_config,
            parent_data_map=_add_channel_path,
            parent_endpoint_extra={"data_selector_required": True},
            child_endpoint_extra={"data_selector_required": True},
            child_params_extra=dict(endpoint_config.params),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            should_use_incremental_field=should_use_incremental_field,
            incremental_field=incremental_field,
            incremental_config_factory=_incremental_window,
            resume_hook=lambda state: _save_fanout_state(resumable_source_manager, state),
            initial_paginator_state=resume_state.fanout_state if resume_state else None,
        )
        row_map = _CHILD_ROW_MAPS.get(endpoint)

        def child_items() -> Iterable[Any]:
            return _map_pages(child, row_map) if row_map else child

        return _make_source_response(endpoint_config, child_items)

    config: RESTAPIConfig = {
        "client": client_config,
        "resource_defaults": {},
        "resources": [get_resource(endpoint, unit, should_use_incremental_field, incremental_field)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=lambda state: _save_next_url(resumable_source_manager, state),
        initial_paginator_state=(
            {"next_url": resume_state.next_url} if resume_state and resume_state.next_url else None
        ),
    )
    return _make_source_response(endpoint_config, lambda: resource, resource.column_hints)


def _load_resume_state(
    resumable_source_manager: ResumableSourceManager[AblyResumeConfig],
) -> Optional[AblyResumeConfig]:
    if not resumable_source_manager.can_resume():
        return None
    return resumable_source_manager.load_state()


def _save_next_url(
    resumable_source_manager: ResumableSourceManager[AblyResumeConfig], state: Optional[dict[str, Any]]
) -> None:
    if state and state.get("next_url"):
        resumable_source_manager.save_state(AblyResumeConfig(next_url=str(state["next_url"])))


def _save_fanout_state(
    resumable_source_manager: ResumableSourceManager[AblyResumeConfig], state: Optional[dict[str, Any]]
) -> None:
    if state:
        resumable_source_manager.save_state(AblyResumeConfig(fanout_state=state))


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, str | None]:
    username, password = split_api_key(api_key)
    if not password:
        return False, "Ably API key is malformed — expected the format `{app-id}.{key-id}:{key-secret}`."

    session = make_tracked_session(headers=version_header(api_version), redact_values=(password, api_key))
    try:
        response = session.get(
            f"{BASE_URL}/stats",
            params={"limit": 1},
            auth=(username, password),
        )
    except RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Ably authentication failed. Please check your API key."
    return False, f"Ably returned an unexpected status code ({response.status_code})."
