import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.greenhouse.settings import (
    GREENHOUSE_ENDPOINTS,
    GreenhouseEndpointConfig,
)

GREENHOUSE_BASE_URL = "https://harvest.greenhouse.io/v1"
# Harvest's documented maximum page size. Fewer requests keeps us comfortably under the
# per-10-second rate limit advertised via the `X-RateLimit-*` response headers.
PAGE_SIZE = 500


@dataclasses.dataclass
class GreenhouseResumeConfig:
    # Harvest paginates with RFC 5988 `Link` headers. We persist the full `rel="next"` URL
    # (it already carries `per_page` plus any timestamp filter) so a resumed run continues
    # from the same page rather than restarting the stream.
    next_url: str


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 string Harvest's `*_after` filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00.000Z")
    return str(value)


def _build_initial_params(
    config: GreenhouseEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        filter_param = config.incremental_filter_params.get(incremental_field)
        if filter_param:
            # Harvest's `*_after` filters are inclusive — merge dedupes the boundary rows.
            params[filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def validate_credentials(
    api_key: str, path: str = "/candidates", accept_forbidden: bool = True
) -> tuple[bool, str | None]:
    """Probe a Harvest endpoint to confirm the API key is genuine.

    Harvest keys are scoped per-resource: a valid key may still 403 on an endpoint it wasn't
    granted. At source-create time (``accept_forbidden=True``) we treat 403 as success so users
    can connect with keys scoped only to the endpoints they want; per-schema checks pass
    ``accept_forbidden=False`` to surface a missing-scope error for that specific endpoint.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{GREENHOUSE_BASE_URL}{path}?per_page=1",
        auth=HTTPBasicAuth(api_key, ""),
    )

    if status == 200:
        return True, None

    if status == 403:
        if accept_forbidden:
            return True, None
        return False, "Your Greenhouse API key does not have permission to access this endpoint."

    if status == 401:
        return False, "Invalid Greenhouse API key. Please check your key and try again."

    if status is None:
        return False, "Could not reach the Greenhouse API. Please try again."

    return False, f"Greenhouse API returned an unexpected status code: {status}"


def greenhouse_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[GreenhouseResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = GREENHOUSE_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": GREENHOUSE_BASE_URL,
            # Harvest uses HTTP Basic auth with the API key as the username and a blank password.
            # Supplied via framework auth so the key is redacted from logs and error messages.
            "auth": {"type": "http_basic", "username": api_key, "password": ""},
            # Harvest paginates with RFC 5988 `Link` headers; the paginator follows the
            # `rel="next"` URL verbatim (it already encodes per_page + filters).
            "paginator": HeaderLinkPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(GreenhouseResumeConfig(next_url=str(state["next_url"])))

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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Harvest orders list results by `id`, not by the timestamp cursor, so there is no way
        # to request ascending-by-cursor ordering. We keep `asc` (the watermark advances to the
        # max cursor value seen) and rely on the resumable `Link` cursor to make in-run retries
        # safe; merge semantics dedupe re-fetched rows.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
