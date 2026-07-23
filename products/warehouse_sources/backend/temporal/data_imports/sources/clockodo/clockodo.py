import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_ENDPOINTS,
    ENTRIES_TIME_SINCE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

# Clockodo's API is hosted at a single fixed host for every account (no per-tenant subdomain).
CLOCKODO_BASE_URL = "https://my.clockodo.com/api"

# Clockodo identifies the calling application via a mandatory header formatted
# "[application name];[email address]". We send our app name plus the connecting user's email.
EXTERNAL_APPLICATION_NAME = "PostHog"


@dataclasses.dataclass
class ClockodoResumeConfig:
    # Next 1-indexed page to fetch. Only meaningful for paginated endpoints.
    next_page: int


def _build_headers(api_user: str) -> dict[str, str]:
    # The API key is supplied via the framework auth config so its value is redacted from
    # logs; only the non-secret identification/accept headers are set here.
    return {
        "X-ClockodoApiUser": api_user,
        "X-Clockodo-External-Application": f"{EXTERNAL_APPLICATION_NAME};{api_user}",
        "Accept": "application/json",
    }


def _format_z(dt: datetime) -> str:
    """ISO 8601 in UTC with a Z suffix, the format the entries endpoint expects."""
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _endpoint_params(endpoint: str) -> dict[str, Any]:
    config = CLOCKODO_ENDPOINTS[endpoint]
    params: dict[str, Any] = dict(config.extra_params)
    if endpoint == "entries":
        # Send a wide window so every entry is in range. time_until is pushed a year past now
        # to also capture future-dated planned entries.
        params["time_since"] = ENTRIES_TIME_SINCE
        params["time_until"] = _format_z(datetime.now(UTC) + timedelta(days=365))
    return params


def clockodo_source(
    api_user: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ClockodoResumeConfig],
) -> SourceResponse:
    config = CLOCKODO_ENDPOINTS[endpoint]

    # Clockodo only paginates a subset of resources; paginated responses carry the total
    # page count at paging.count_pages, so we stop after the last page. An empty page also
    # terminates (stop_after_empty_page default).
    paginator: BasePaginator = (
        PageNumberPaginator(base_page=1, page_param="page", total_path="paging.count_pages")
        if config.paginated
        else SinglePagePaginator()
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": CLOCKODO_BASE_URL,
            "headers": _build_headers(api_user),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-ClockodoApiKey", "location": "header"},
            "paginator": paginator,
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _endpoint_params(endpoint),
                    "data_selector": config.data_key,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash
        # re-fetches the last in-flight page (merge dedupes on the primary key) rather than
        # skipping it. Unpaginated endpoints never produce a state, so they never checkpoint.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(ClockodoResumeConfig(next_page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Clockodo endpoint is full refresh — no incremental fields
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
    )


def validate_credentials(api_user: str, api_key: str) -> bool:
    """Cheap probe to confirm the API user/key pair is genuine."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{CLOCKODO_BASE_URL}/v2/users",
        headers={"X-ClockodoApiKey": api_key, **_build_headers(api_user)},
    )
    return ok
