import re
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests.exceptions import RequestException

from products.warehouse_sources.sources.bird.settings import (
    BASE_URL_TEMPLATE,
    BIRD_ENDPOINTS,
    DAILY_STATS_WINDOW_DAYS,
    DEFAULT_REGION,
    PAGE_SIZE,
    BirdEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    EndpointResource,
    JSONResponseCursorPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    capture_exception,
    frozen,
    make_tracked_session,
    rest_api_resource,
)

INVALID_KEY_FORMAT_ERROR = (
    "That doesn't look like a Bird API key. Bird API keys start with `bk_` and the region, "
    "for example `bk_us1_` or `bk_eu1_`. Copy the whole key from the Bird dashboard."
)
INVALID_KEY_ERROR = (
    "Bird rejected your API key. Check that the key is not revoked or expired, "
    "or create a new key in the Bird dashboard under Platform tools > API keys."
)
WRONG_REGION_ERROR = (
    "Bird says your API key belongs to a different region than its prefix shows. "
    "Copy the whole key from the Bird dashboard, then try again."
)
UNREACHABLE_ERROR = "PostHog couldn't reach Bird to check your API key. Wait a few minutes, then try again."
UNVERIFIED_KEY_ERROR = "PostHog couldn't verify your Bird API key. Check the key, then try again."

# A key starts with `bk_{region}_`. The region becomes part of the host name, so it must match Bird's
# region code format exactly (two letters and an instance digit, such as `us1`). That keeps the key
# from sending requests to any host outside `*.platform.bird.com`.
_KEY_RE = re.compile(r"^bk_(?P<region>[a-z]{2}[0-9]+)_\S+$")

# (connect, read) seconds for the one-request credential probe.
PROBE_TIMEOUT = (10, 30)


@frozen
class BirdResumeConfig:
    # The `next_cursor` of the last page already read, sent back as `starting_after`.
    starting_after: Optional[str] = None


def region_from_api_key(api_key: str) -> Optional[str]:
    match = _KEY_RE.match(api_key.strip())
    return match.group("region") if match else None


def base_url(api_key: str) -> str:
    # A key without a region prefix goes to Bird's default region, which answers it with a 401 or with a
    # 421 that names the right host. The host stays on platform.bird.com either way.
    return BASE_URL_TEMPLATE.format(region=region_from_api_key(api_key) or DEFAULT_REGION)


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": base_url(api_key),
        "auth": {"type": "bearer", "token": api_key.strip()},
        # The bearer key must never follow a redirect to another host.
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    return str(value)


def _daily_stats_window(today: date) -> dict[str, str]:
    start = today - timedelta(days=DAILY_STATS_WINDOW_DAYS - 1)
    return {"from": start.isoformat(), "to": today.isoformat()}


def _request_params(
    config: BirdEndpointConfig,
    db_incremental_field_last_value: Any,
    today: date,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.params)
    if config.paginated:
        params["limit"] = PAGE_SIZE
    if config.daily_stats:
        params.update(_daily_stats_window(today))
    if config.incremental_param and db_incremental_field_last_value is not None:
        params[config.incremental_param] = _format_timestamp(db_incremental_field_last_value)
    return params


def _paginator(config: BirdEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    # `next_cursor` is null on the last page. A cursor that repeats means the listing is not moving,
    # so fail instead of reading the same page forever.
    return JSONResponseCursorPaginator(
        cursor_path="next_cursor", cursor_param="starting_after", raise_on_repeated_cursor=True
    )


def get_resource(config: BirdEndpointConfig, params: dict[str, Any], incremental: bool) -> EndpointResource:
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if incremental else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": "data",
            "data_selector_required": True,
            "paginator": _paginator(config),
        },
        "table_format": "delta",
    }


def _save_paginator_state(manager: ResumableSourceManager[BirdResumeConfig], state: Optional[dict[str, Any]]) -> None:
    if state and state.get("cursor"):
        manager.save_state(BirdResumeConfig(starting_after=str(state["cursor"])))


def bird_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BirdResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    today: Optional[date] = None,
) -> SourceResponse:
    config = BIRD_ENDPOINTS.get(endpoint)
    if config is None:
        raise ValueError(f"Unknown Bird endpoint: {endpoint}")

    incremental = should_use_incremental_field and bool(config.incremental_fields)
    params = _request_params(
        config,
        db_incremental_field_last_value if incremental else None,
        today or datetime.now(UTC).date(),
    )

    resume_state = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    initial_paginator_state = (
        {"cursor": resume_state.starting_after}
        if config.paginated and resume_state is not None and resume_state.starting_after
        else None
    )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(config, params, incremental)],
    }
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=lambda state: _save_paginator_state(resumable_source_manager, state),
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        column_hints=resource.column_hints,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    config = BIRD_ENDPOINTS.get(schema_name or "contacts", BIRD_ENDPOINTS["contacts"])
    key = api_key.strip()
    session = make_tracked_session(redact_values=(key,))
    try:
        response = session.get(
            f"{base_url(key)}{config.path}",
            # The daily stats endpoints reject `limit` and default to the last 30 days.
            params={"limit": 1} if config.paginated else None,
            headers={"Authorization": f"Bearer {key}"},
            allow_redirects=False,
            timeout=PROBE_TIMEOUT,
        )
    except RequestException:
        return False, UNREACHABLE_ERROR

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        # A key from MessageBird or the older Bird platform has no `bk_` prefix.
        return False, INVALID_KEY_ERROR if region_from_api_key(key) else INVALID_KEY_FORMAT_ERROR
    if response.status_code == 403:
        # The key is genuine but lacks the scope of this table. A key may cover only the tables the
        # user wants, so this blocks only the check of one table, not the source.
        if schema_name is None:
            return True, None
        return False, (
            f"Your Bird API key can't read the {config.name} table. Give the key read access to it "
            "in the Bird dashboard under Platform tools > API keys, or don't sync this table."
        )
    if response.status_code == 421:
        return False, WRONG_REGION_ERROR
    capture_exception(Exception(f"Unexpected Bird credential validation response ({response.status_code})"))
    return False, UNVERIFIED_KEY_ERROR
