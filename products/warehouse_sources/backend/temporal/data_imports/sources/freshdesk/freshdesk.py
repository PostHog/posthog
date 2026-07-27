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
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.settings import (
    FRESHDESK_ENDPOINTS,
    PER_PAGE,
    FreshdeskEndpointConfig,
)

VALIDATE_TIMEOUT = 10


@dataclasses.dataclass
class FreshdeskResumeConfig:
    next_url: str


def normalize_subdomain(domain: str) -> str:
    """Accept either a bare subdomain ("acme") or a full host ("acme.freshdesk.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshdesk.com")


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.freshdesk.com"


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Freshdesk expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_params(
    config: FreshdeskEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PER_PAGE}
    params.update(config.extra_params)

    if should_use_incremental_field and config.updated_since_param and db_incremental_field_last_value:
        params[config.updated_since_param] = _format_updated_since(db_incremental_field_last_value)

    return params


def freshdesk_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FreshdeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FRESHDESK_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": _base_url(subdomain),
            "headers": {"Content-Type": "application/json"},
            # Freshdesk uses HTTP Basic auth with the API key as the username and any
            # non-empty string as the password. Supplied via framework auth so the value
            # is redacted from logs.
            "auth": {"type": "http_basic", "username": api_key, "password": "X"},
            # Freshdesk paginates with an RFC 5988 `Link: ...; rel="next"` header.
            "paginator": HeaderLinkPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _build_params(config, should_use_incremental_field, db_incremental_field_last_value),
                    # Most list endpoints return a bare array; a few (e.g. skills) wrap it in an object.
                    "data_selector": config.data_key,
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
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(FreshdeskResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> Optional[int]:
    """Probe the Freshdesk API. Returns the HTTP status code, or ``None`` on a connection error."""
    url = f"{_base_url(subdomain)}/api/v2/tickets?per_page=1"
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        url,
        auth=HTTPBasicAuth(api_key, "X"),
        timeout=VALIDATE_TIMEOUT,
    )
    return status
