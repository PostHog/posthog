import time
import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional

from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.settings import BASE_URL, MAX_LIMIT
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager


@dataclasses.dataclass
class AblyResumeConfig:
    next_url: str


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


def get_resource(unit: str, should_use_incremental_field: bool) -> EndpointResource:
    endpoint: Endpoint = {
        "path": "/stats",
        "paginator": "header_link",
        "params": {
            "unit": unit,
            "direction": "forwards",
            "limit": MAX_LIMIT,
        },
        "data_selector_required": True,
    }

    if should_use_incremental_field:
        incremental_config: IncrementalConfig = {
            "start_param": "start",
            "end_param": "end",
            "initial_value": "0",
            # Ably has no open-ended "everything since X" mode — every request needs an
            # explicit end. Bound it to "now" at request-build time (this function runs
            # fresh each sync) rather than relying on the vendor's own end-of-window default.
            "end_value": str(int(time.time() * 1000)),
        }
        endpoint["incremental"] = incremental_config

    return {
        "name": "Stats",
        "table_name": "stats",
        "write_disposition": {
            "disposition": "merge",
            "strategy": "upsert",
        }
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
        "data_map": _add_interval_start,
    }


def ably_source(
    api_key: str,
    unit: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AblyResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
):
    username, password = split_api_key(api_key)

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
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
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if should_use_incremental_field
            else "replace",
        },
        "resources": [get_resource(unit, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("next_url"):
            resumable_source_manager.save_state(AblyResumeConfig(next_url=str(state["next_url"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    username, password = split_api_key(api_key)
    if not password:
        return False, "Ably API key is malformed — expected the format `{app-id}.{key-id}:{key-secret}`."

    session = make_tracked_session(redact_values=(password, api_key))
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
