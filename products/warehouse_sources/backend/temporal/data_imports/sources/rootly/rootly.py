import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.settings import (
    ROOTLY_ENDPOINTS,
    RootlyEndpointConfig,
)

ROOTLY_BASE_URL = "https://api.rootly.com/v1"
# Rootly is a JSON:API service and expects/returns the JSON:API media type.
ROOTLY_JSON_API_MEDIA_TYPE = "application/vnd.api+json"


@dataclasses.dataclass
class RootlyResumeConfig:
    # Full next-page URL from the JSON:API `links.next` field. It already carries the page,
    # sort, and filter params, so following it preserves the incremental window on every page.
    next_url: str | None = None


def _accept_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret JSON:API Accept header is set here.
    return {"Accept": ROOTLY_JSON_API_MEDIA_TYPE}


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL. Rootly is Rails/JSON:API and parses percent-encoded bracket params
    (`filter[updated_at][gt]`, `page[size]`) correctly, so standard urlencode is safe."""
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp for Rootly's date filters."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now. A future-dated record could push the cursor
    past now; asking for records newer than now is a no-op, so clamping keeps the filter sane."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: RootlyEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for the first request to a Rootly collection endpoint."""
    params: dict[str, Any] = {"page[size]": config.page_size}

    if config.supports_incremental and should_use_incremental_field:
        # Cursor on the user's chosen field; fall back to the endpoint's first advertised field.
        field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
        if field_name:
            # Sort ascending on the same field we filter on so rows arrive in watermark order and
            # the pipeline can checkpoint safely (matches SourceResponse.sort_mode="asc").
            params["sort"] = field_name
            if db_incremental_field_last_value:
                value = _clamp_future_value_to_now(db_incremental_field_last_value)
                params[f"filter[{field_name}][gt]"] = _format_incremental_value(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


def probe_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Rootly collection. Returns the HTTP status code, or None on a connection
    failure. Probes the given endpoint's path when set, else a generic, cheap collection."""
    config = ROOTLY_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/users"
    url = _build_url(f"{ROOTLY_BASE_URL}{path}", {"page[size]": 1})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        headers={"Authorization": f"Bearer {api_key}", **_accept_headers()},
    )
    return status


def rootly_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ROOTLY_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ROOTLY_BASE_URL,
            "headers": _accept_headers(),
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs.
            "auth": {"type": "bearer", "token": api_key},
            # Rootly is JSON:API — the next page URL lives in the response body under `links.next`.
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # A 200 body without `data` is treated as an empty page (JSON:API always carries
                    # `data`), matching the old `data.get("data", [])` — so no data_selector_required.
                    "data_selector": "data",
                },
                # Rootly is JSON:API — hoist each item's `attributes` into the row root.
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
            resumable_source_manager.save_state(RootlyResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Incremental filtering is applied server-side via the `filter[<field>][gt]` param built into
        # `params` above, so the framework's own incremental injection is not used here.
        None,
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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
