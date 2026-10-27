import re
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    HeaderLinkPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.megaphone.settings import (
    MEGAPHONE_BASE_URL,
    MEGAPHONE_ENDPOINTS,
    MEGAPHONE_HOST,
    MegaphoneEndpointConfig,
)

# The organization id goes into the request path, so it must stay a single path segment.
_ORGANIZATION_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
_ISO_UTC = "%Y-%m-%dT%H:%M:%S.000Z"


@frozen
class MegaphoneResumeConfig:
    # Next-page link from the `Link` header of a top-level list.
    next_url: Optional[str] = None
    # `build_dependent_resource` checkpoint for the per-network podcast walk.
    fanout_state: Optional[dict[str, Any]] = None


def is_valid_organization_id(organization_id: str) -> bool:
    return bool(_ORGANIZATION_ID_RE.match(organization_id))


def auth_header_value(api_token: str) -> str:
    return f'Token token="{api_token}"'


def format_filter_min(value: Any) -> str:
    parsed = parse_datetime_value(value)
    if parsed is None:
        raise ValueError(f"Cannot use {value!r} as a Megaphone updatedAt filter")
    return parsed.strftime(_ISO_UTC)


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": MEGAPHONE_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "name": "Authorization", "api_key": auth_header_value(api_token)},
        "paginator": HeaderLinkPaginator(),
        # The resume cursor is a full URL from the `Link` header, so pin it to Megaphone.
        "allowed_hosts": [MEGAPHONE_HOST],
        "allow_redirects": False,
    }


def get_resource(config: MegaphoneEndpointConfig, organization_id: str, is_incremental: bool) -> EndpointResource:
    params: dict[str, Any] = {"per_page": config.page_size}
    if config.organization_param:
        params[config.organization_param] = organization_id
    params.update((config.incremental_params if is_incremental else config.full_refresh_params) or {})
    if is_incremental and config.incremental_param and config.default_incremental_field:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.default_incremental_field,
            "initial_value": "1970-01-01T00:00:00.000Z",
            "convert": format_filter_min,
        }
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": {"path": config.path.replace("{organization_id}", organization_id), "params": params},
        "table_format": "delta",
    }


def megaphone_source(
    api_token: str,
    organization_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MegaphoneResumeConfig],
    db_incremental_field_last_value: Optional[Any],
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    if not is_valid_organization_id(organization_id):
        raise ValueError("Invalid Megaphone organization ID")

    config = MEGAPHONE_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and bool(config.incremental_fields)
    client_config = _client_config(api_token)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.fanout is not None:

        def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state:
                resumable_source_manager.save_state(MegaphoneResumeConfig(fanout_state=state))

        resource: Any = build_dependent_resource(
            endpoint_configs=MEGAPHONE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={"organization_id": organization_id},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="per_page",
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=resume.fanout_state if resume else None,
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client_config,
            "resource_defaults": {},
            "resources": [get_resource(config, organization_id, is_incremental)],
        }

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            if state and state.get("next_url"):
                resumable_source_manager.save_state(MegaphoneResumeConfig(next_url=str(state["next_url"])))

        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            db_incremental_field_last_value,
            resume_hook=save_checkpoint,
            initial_paginator_state={"next_url": resume.next_url} if resume and resume.next_url else None,
        )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # The episode search always returns the most recently updated episodes first.
        sort_mode="desc" if is_incremental else "asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def probe_credentials(api_token: str, organization_id: str) -> tuple[bool, int | None]:
    value = auth_header_value(api_token)
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token, value)),
        f"{MEGAPHONE_BASE_URL}/organizations/{organization_id}/networks?per_page=1",
        headers={"Authorization": value, "Accept": "application/json"},
        allow_redirects=False,
    )
