import dataclasses
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.sources.aftership.settings import (
    AFTERSHIP_BASE_URL,
    AFTERSHIP_ENDPOINTS,
    DEFAULT_VERSION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# AfterShip authenticates every request with the API key in this header. The legacy
# `aftership-api-key` header stopped working with the 2023-10 version.
API_KEY_HEADER = "as-api-key"

VALIDATION_TIMEOUT_SECONDS = 15


@dataclasses.dataclass
class AftershipResumeConfig:
    # Cursor of the next unread page, replayed as `cursor` on the resumed request.
    cursor: str
    # The time-filter value the interrupted run was using, reused verbatim on resume. The
    # watermark may have advanced from committed batches, and narrowing the window mid-walk
    # would hand AfterShip a cursor that points outside the filtered result set.
    incremental_start: Optional[str] = None


def base_url(api_version: str) -> str:
    return f"{AFTERSHIP_BASE_URL}/{api_version}"


def _to_aftership_datetime(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value into the exact shape AfterShip's time filters accept.

    `created_at_min` / `updated_at_min` are validated against
    `YYYY-MM-DDTHH:mm:ss+HH:MM`, so a trailing `Z` or fractional seconds is rejected with a 400.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.replace(microsecond=0).isoformat()


def _drop_courier_connection_credentials(row: dict[str, Any]) -> dict[str, Any]:
    # `credentials` carries the carrier API keys, usernames and passwords the user handed to
    # AfterShip. They are login secrets rather than shipment analytics, so they never reach the
    # warehouse, where any project member could query them.
    return {key: value for key, value in row.items() if key != "credentials"}


def check_access(
    api_key: str,
    schema_name: Optional[str] = None,
    api_version: str = DEFAULT_VERSION,
) -> tuple[bool, Optional[int]]:
    """Probe AfterShip and report ``(is_valid, status_code)``.

    With no ``schema_name`` this only proves the key is genuine; with one it proves the key can
    read that endpoint. ``limit=1`` keeps the probe off the per-endpoint rate-limit budget.
    """
    endpoint = AFTERSHIP_ENDPOINTS[schema_name] if schema_name is not None else AFTERSHIP_ENDPOINTS["trackings"]
    query = urlencode({"limit": 1}) if endpoint.cursor_paginated else ""
    url = f"{base_url(api_version)}{endpoint.path}"
    if query:
        url = f"{url}?{query}"

    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={API_KEY_HEADER: api_key},
        timeout=VALIDATION_TIMEOUT_SECONDS,
        # The key rides a custom header, which `requests` would replay to a cross-origin redirect.
        allow_redirects=False,
    )


def aftership_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AftershipResumeConfig],
    should_use_incremental_field: bool = False,
    incremental_field_name: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
    api_version: str = DEFAULT_VERSION,
) -> SourceResponse:
    config = AFTERSHIP_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        initial_paginator_state = {"cursor": resume.cursor}
        incremental_start = resume.incremental_start
    else:
        incremental_start = (
            _to_aftership_datetime(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value is not None
            else None
        )

    # The user's chosen incremental field decides which server-side filter we send. A field with
    # no matching filter (or an endpoint with none at all) syncs the full window instead of
    # pretending to filter.
    incremental_param = config.incremental_params.get(incremental_field_name or "")

    params: dict[str, Any] = dict(config.extra_params)
    if incremental_param is not None and incremental_start is not None:
        params[incremental_param] = incremental_start

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            "auth": {"type": "api_key", "name": API_KEY_HEADER, "location": "header", "api_key": api_key},
            "paginator": JSONResponseCursorPaginator(cursor_path="data.pagination.next_cursor", cursor_param="cursor")
            if config.cursor_paginated
            else SinglePagePaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": config.data_selector,
                },
                **({"data_map": _drop_courier_connection_credentials} if endpoint == "courier_connections" else {}),
            }
        ],
    }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains. The framework calls this AFTER a page is
        # yielded, so a crash re-yields the last page (merge dedupes on the primary key) rather
        # than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(
                AftershipResumeConfig(cursor=str(state["cursor"]), incremental_start=incremental_start)
            )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # The time window is written into `params` above (a resumed run must reuse the saved
        # window verbatim), so the framework's own incremental plumbing stays out of the way.
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_key,
        # AfterShip documents no ordering for its list endpoints and offers no sort parameter, so
        # we can't claim rows arrive oldest-first. `desc` is the safe reading of an unknown order:
        # the pipeline commits the watermark once at the end of the sync from the highest value it
        # saw, instead of checkpointing each batch as if the stream were ascending.
        sort_mode="desc",
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
