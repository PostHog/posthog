import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

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
from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.settings import (
    PRODUCTBOARD_ENDPOINTS,
)

PRODUCTBOARD_BASE_URL = "https://api.productboard.com/v2"


@dataclasses.dataclass
class ProductboardResumeConfig:
    # Full URL of the next unfetched page — Productboard returns it in the `links.next` body field.
    next_url: str


def _non_secret_headers() -> dict[str, str]:
    # Bearer auth is supplied via the framework auth config so its value is redacted from logs and
    # error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a `Z` suffix.

    Productboard's date/time filters expect ISO 8601 date-time strings; we normalise
    to UTC so naive watermarks from the DB compare correctly against tz-aware values.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)

    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_initial_params(
    endpoint: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    config = PRODUCTBOARD_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}

    if config.entity_type:
        # The `type[]` bracket key percent-encodes on the wire (`type%5B%5D=...`), which is
        # what Productboard's `/entities` filter expects.
        params["type[]"] = config.entity_type

    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        field = incremental_field or config.default_incremental_field
        filter_param = config.incremental_param_map.get(field) if field else None
        if filter_param:
            params[filter_param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def productboard_source(
    access_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ProductboardResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = PRODUCTBOARD_ENDPOINTS[endpoint]

    params = _build_initial_params(
        endpoint, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": PRODUCTBOARD_BASE_URL,
            "headers": _non_secret_headers(),
            "auth": {"type": "bearer", "token": access_token},
            # Next-page URL lives in the response body under `links.next`; absence of it ends the sync.
            "paginator": JSONResponsePaginator(next_url_path="links.next"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(ProductboardResumeConfig(next_url=state["next_url"]))

    # The incremental watermark is applied by `_build_initial_params` as a Productboard-specific server
    # filter param, so the framework's generic incremental injection is not used here.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(access_token: str, path: str) -> tuple[bool, int | None]:
    """Probe a single Productboard endpoint. Returns (ok, status_code)."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_token,)),
        f"{PRODUCTBOARD_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}", **_non_secret_headers()},
    )
