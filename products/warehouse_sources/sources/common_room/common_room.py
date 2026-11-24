import math
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Optional

import requests
from requests import Response
from requests.exceptions import RequestException

from products.warehouse_sources.sources.common_room.settings import (
    BASE_URL,
    COMMON_ROOM_ENDPOINTS,
    CommonRoomEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    coerce_datetime_to_utc,
    make_tracked_session,
    rest_api_resources,
)

VALIDATION_TIMEOUT_SECONDS = 30

INVALID_TOKEN_MESSAGE = (
    "Common Room rejected your API token. Create a new token in Common Room under "
    "Settings > API tokens, then reconnect the source."
)
RATE_LIMITED_MESSAGE = "Common Room is rate limiting this API token. Wait a minute, then try again."
UNREACHABLE_MESSAGE = "Couldn't reach Common Room. Try again in a few minutes."


@dataclasses.dataclass(frozen=True)
class CommonRoomResumeConfig:
    # The REST framework's paginator state: `{"cursor": ...}` for a list endpoint, or the fan-out
    # state (finished parents and the cursor of the current one) for `objects`.
    paginator_state: dict[str, Any]


def retry_after_from_wait_ms(response: Response, *args: Any, **kwargs: Any) -> Response:
    """Turn the wait of a Common Room 429 into a `Retry-After` delay that the REST client reads.

    Common Room puts the wait in the body (`rateLimit.waitMs`), and its `Retry-After` header holds an
    ISO 8601 instant that the client cannot parse, so without this hook a 429 backs off blind.
    """
    if response.status_code != 429:
        return response
    wait_seconds: Optional[float] = None
    try:
        body = response.json()
    except ValueError:
        body = None
    rate_limit = body.get("rateLimit") if isinstance(body, dict) else None
    wait_ms = rate_limit.get("waitMs") if isinstance(rate_limit, dict) else None
    if isinstance(wait_ms, int | float) and not isinstance(wait_ms, bool) and wait_ms >= 0:
        wait_seconds = wait_ms / 1000
    else:
        header = response.headers.get("Retry-After")
        if header:
            try:
                reset_at = datetime.fromisoformat(header.strip().replace("Z", "+00:00"))
            except ValueError:
                reset_at = None
            if reset_at is not None:
                if reset_at.tzinfo is None:
                    reset_at = reset_at.replace(tzinfo=UTC)
                wait_seconds = max(0.0, (reset_at - datetime.now(UTC)).total_seconds())
    if wait_seconds is not None:
        # At least one second, so the next try does not land in the same window.
        response.headers["Retry-After"] = str(max(1, math.ceil(wait_seconds)))
    return response


def _session(api_token: str) -> requests.Session:
    # Rows hold contact names, emails and phone numbers, so no sample capture.
    session = make_tracked_session(redact_values=(api_token,), capture=False)
    session.hooks["response"].append(retry_after_from_wait_ms)
    return session


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
        "session": _session(api_token),
    }


def format_start_date(value: Any) -> str:
    """Format the watermark as the ISO 8601 UTC instant that `startDate` takes."""
    normalized = coerce_datetime_to_utc(value)
    if normalized is None:
        return str(value)
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _endpoint(config: CommonRoomEndpointConfig) -> Endpoint:
    params: dict[str, Any] = dict(config.params)
    if config.paginated:
        params["limit"] = config.page_size
    if config.columns:
        params["cols"] = ",".join(config.columns)
    path = config.path
    if config.parent is not None and config.resolve_param is not None:
        # The framework resolves a parent value only into the path, so the filter rides in the path.
        path = f"{config.path}?{config.resolve_param}={{{config.resolve_param}}}"
        params[config.resolve_param] = {"type": "resolve", "resource": config.parent, "field": "id"}
    endpoint: Endpoint = {
        "path": path,
        "data_selector": "data",
        "data_selector_required": True,
        "params": params,
    }
    # Each endpoint names its paginator, because a fan-out child does not get the client default.
    endpoint["paginator"] = (
        JSONResponseCursorPaginator(cursor_path="meta.nextCursor", cursor_param="cursor")
        if config.paginated
        else "single_page"
    )
    return endpoint


def get_resource(
    config: CommonRoomEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    use_incremental = should_use_incremental_field and bool(config.incremental_fields)
    endpoint = _endpoint(config)
    # The first incremental sync sends no filter, so it reads the full history.
    if use_incremental and db_incremental_field_last_value is not None:
        endpoint["incremental"] = {
            "cursor_path": "activityTime",
            "start_param": "startDate",
            "initial_value": None,
            "convert": format_start_date,
        }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    if config.parent is not None:
        resource["include_from_parent"] = ["id"]
    return resource


def _rename_parent_id(parent: str, target: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    key = f"_{parent}_id"

    def rename(row: dict[str, Any]) -> dict[str, Any]:
        if key in row:
            row[target] = row.pop(key)
        return row

    return rename


def common_room_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CommonRoomResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = COMMON_ROOM_ENDPOINTS[endpoint]
    use_incremental = should_use_incremental_field and bool(endpoint_config.incremental_fields)

    resources: list[str | EndpointResource] = []
    if endpoint_config.parent is not None:
        parent_config = COMMON_ROOM_ENDPOINTS[endpoint_config.parent]
        resources.append(get_resource(parent_config, False, None))
    resources.append(get_resource(endpoint_config, should_use_incremental_field, db_incremental_field_last_value))

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": resources,
    }

    resume_kwargs: dict[str, Any] = {}
    # The one-page endpoints have nothing to resume.
    if endpoint_config.paginated:
        initial_paginator_state: Optional[dict[str, Any]] = None
        if resumable_source_manager.can_resume():
            resume_config = resumable_source_manager.load_state()
            if resume_config is not None:
                initial_paginator_state = resume_config.paginator_state

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(CommonRoomResumeConfig(paginator_state=state))

        resume_kwargs = {"resume_hook": save_checkpoint, "initial_paginator_state": initial_paginator_state}

    built = rest_api_resources(rest_config, team_id, job_id, db_incremental_field_last_value, **resume_kwargs)
    resource = next(item for item in built if item.name == endpoint_config.name)
    if endpoint_config.parent is not None and endpoint_config.resolve_param is not None:
        resource = resource.add_map(_rename_parent_id(endpoint_config.parent, endpoint_config.resolve_param))

    partition_key = endpoint_config.partition_key
    return SourceResponse(
        name=endpoint_config.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        # Activities are requested with `sort=activityTime&direction=asc`, one cursor series.
        sort_mode="asc" if use_incremental else None,
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session(redact_values=(api_token,), capture=False).get(
            f"{BASE_URL}/api-token-status",
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
            timeout=VALIDATION_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except RequestException:
        return False, UNREACHABLE_MESSAGE

    status = response.status_code
    if status == 200:
        return True, None
    # Common Room answers a token that is not valid with a 403, not a 401.
    if status in (401, 403):
        return False, INVALID_TOKEN_MESSAGE
    if status == 429:
        return False, RATE_LIMITED_MESSAGE
    return False, f"Common Room returned an unexpected response (HTTP {status}). Try again in a few minutes."
