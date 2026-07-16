import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.calendly.settings import (
    CALENDLY_ENDPOINTS,
    CalendlyEndpointConfig,
)
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

CALENDLY_BASE_URL = "https://api.calendly.com"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 60


@dataclasses.dataclass
class CalendlyResumeConfig:
    next_url: str


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC string, which Calendly's time filters expect."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return str(value)


def _get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def validate_credentials(token: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(token,)),
        f"{CALENDLY_BASE_URL}/users/me",
        headers=_get_headers(token),
    )
    return ok


def get_current_organization(token: str) -> str:
    """Resolve the organization URI for the token via `/users/me`.

    Every list endpoint we sync is scoped by this URI, so we access it directly and let a
    malformed response surface immediately as a KeyError rather than degrading to None.
    """
    response = make_tracked_session(redact_values=(token,)).get(
        f"{CALENDLY_BASE_URL}/users/me", headers=_get_headers(token), timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.json()["resource"]["current_organization"]


def _build_initial_params(
    config: CalendlyEndpointConfig,
    organization: str | None,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"count": PAGE_SIZE}

    if config.scope_param and organization:
        params[config.scope_param] = organization

    if config.sort:
        params["sort"] = config.sort

    if config.incremental_filter_param and should_use_incremental_field and db_incremental_field_last_value:
        params[config.incremental_filter_param] = _format_datetime(db_incremental_field_last_value)

    return params


def calendly_source(
    token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CalendlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CALENDLY_ENDPOINTS[endpoint]

    def get_rows() -> Iterator[Any]:
        resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

        initial_paginator_state: Optional[dict[str, Any]] = None
        organization: str | None = None
        if resume_config is not None:
            # The saved next-page URL is self-contained, so the `/users/me` bootstrap is skipped.
            initial_paginator_state = {"next_url": resume_config.next_url}
        elif config.scope_param == "organization":
            organization = get_current_organization(token)

        params = _build_initial_params(
            config, organization, should_use_incremental_field, db_incremental_field_last_value
        )

        rest_config: RESTAPIConfig = {
            "client": {
                "base_url": CALENDLY_BASE_URL,
                "headers": {"Content-Type": "application/json"},
                "auth": {"type": "bearer", "token": token},
                "paginator": JSONResponsePaginator(next_url_path="pagination.next_page"),
            },
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": params,
                        # A missing `collection` key is treated as an empty page (matching the API's
                        # tolerant contract); pagination keeps following `next_page` until it's null,
                        # even across empty pages.
                        "data_selector": "collection",
                    },
                }
            ],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only when a next page remains; saved AFTER a page is yielded so a crash
            # re-yields the last page (merge dedupes on `uri`) rather than skipping it.
            if state and state.get("next_url"):
                resumable_source_manager.save_state(CalendlyResumeConfig(next_url=state["next_url"]))

        yield from rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=get_rows,
        primary_keys=["uri"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
