import base64
from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.settings import (
    EPOCH,
    OWNERREZ_ENDPOINTS,
    PAGE_LIMIT,
    OwnerRezEndpointConfig,
)

BASE_URL = "https://api.ownerrez.com"
OWNERREZ_API_HOST = "api.ownerrez.com"
# Required per the vendor's auth guide: "Use a user-agent header to identify yourself on all calls."
USER_AGENT = "PostHog Data Warehouse (+https://posthog.com)"


@frozen
class OwnerRezResumeConfig:
    next_url: str


def _format_since_utc(value: Any) -> str:
    """Format an incremental cursor as the UTC ISO-8601 string OwnerRez's since filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _basic_auth_header(email: str, api_key: str) -> str:
    encoded = base64.b64encode(f"{email}:{api_key}".encode()).decode("ascii")
    return f"Basic {encoded}"


def _build_params(
    config: OwnerRezEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_LIMIT}
    if not config.since_param:
        return params

    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value is not None:
        params[config.since_param] = _format_since_utc(db_incremental_field_last_value)
    elif config.since_required:
        params[config.since_param] = EPOCH

    return params


def ownerrez_source(
    email: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OwnerRezResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    endpoint_config = OWNERREZ_ENDPOINTS[endpoint]
    params = _build_params(endpoint_config, should_use_incremental_field, db_incremental_field_last_value)
    is_incremental = bool(endpoint_config.incremental_fields) and should_use_incremental_field

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"User-Agent": USER_AGENT},
            "auth": {
                "type": "http_basic",
                # OwnerRez's auth guide authenticates with the account email as the username and
                # the personal access token (pt_...) as the password — not the token-as-username
                # form its OpenAPI security scheme description suggests.
                "username": email,
                "password": api_key,
            },
            # The response's `next_page_url` is a self-contained cursor link; follow it verbatim
            # per the vendor's pagination guide rather than incrementing offset/limit by hand.
            "paginator": JSONResponsePaginator(next_url_path="next_page_url"),
            # Pagination follows a URL supplied by the response body, and every request is
            # Basic-authenticated; pin follow-up requests to the API host and refuse redirects so a
            # tampered or spoofed next-page link can't exfiltrate the credentials to another origin.
            "allowed_hosts": [OWNERREZ_API_HOST],
            "allow_redirects": False,
        },
        "resource_defaults": {
            "write_disposition": {
                "disposition": "merge",
                "strategy": "upsert",
            }
            if is_incremental
            else "replace",
        },
        "resources": [
            {
                "name": endpoint_config.name,
                "endpoint": {
                    "data_selector": "items",
                    "path": endpoint_config.path,
                    "params": params,
                },
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"next_url": resume_config.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(OwnerRezResumeConfig(next_url=str(state["next_url"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(email: str, api_key: str) -> tuple[bool, int | None]:
    """Probe the cheap, filter-free /v2/properties list endpoint to confirm the credentials work."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/v2/properties?limit=1",
        headers={"Authorization": _basic_auth_header(email, api_key), "User-Agent": USER_AGENT},
    )
