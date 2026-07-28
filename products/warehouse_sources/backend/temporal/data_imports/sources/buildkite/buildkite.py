import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import (
    BUILDKITE_ENDPOINTS,
    BuildkiteEndpointConfig,
)
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

BUILDKITE_BASE_URL = "https://api.buildkite.com"
# Buildkite caps per_page at 100 (default 30).
PAGE_SIZE = 100


@dataclasses.dataclass
class BuildkiteResumeConfig:
    next_url: str


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as ISO 8601, which Buildkite's *_from filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _resolve_incremental_param(
    config: BuildkiteEndpointConfig,
    incremental_field: str | None,
) -> str | None:
    """Map the user-chosen incremental field to its server-side filter param, if supported."""
    if not config.incremental_param_map:
        return None
    field_name = incremental_field
    if field_name is None and config.incremental_fields:
        field_name = config.incremental_fields[0]["field"]
    if field_name is None:
        return None
    return config.incremental_param_map.get(field_name)


def _build_initial_params(
    config: BuildkiteEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"per_page": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value:
        param = _resolve_incremental_param(config, incremental_field)
        if param:
            params[param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(
    api_access_token: str, organization: str, schema_name: str | None = None
) -> tuple[bool, str | None]:
    """Probe the Buildkite API to confirm the token is genuine and the org is reachable.

    At source-create (``schema_name`` is None) a 403 is accepted: the token is valid but may simply
    lack ``read_organizations`` while still holding the scopes for the endpoints the user wants to
    sync. When checking a specific schema, a 403 means the token can't read that resource, so it
    fails.
    """
    if schema_name and schema_name in BUILDKITE_ENDPOINTS:
        config = BUILDKITE_ENDPOINTS[schema_name]
        path = config.path.format(organization=organization)
        url = f"{BUILDKITE_BASE_URL}{path}?per_page=1"
    else:
        url = f"{BUILDKITE_BASE_URL}/v2/organizations/{organization}"

    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_access_token,)),
        url,
        headers={"Authorization": f"Bearer {api_access_token}", "Accept": "application/json"},
    )

    if ok:
        return True, None
    if status == 401:
        return False, "Invalid Buildkite API access token"
    if status == 403:
        if schema_name:
            return False, f"Your Buildkite API access token lacks the scope needed to read '{schema_name}'"
        return True, None
    if status == 404:
        return False, f"Organization '{organization}' not found or not accessible"
    if status is None:
        return False, "Could not connect to the Buildkite API"
    return False, f"Buildkite API returned an unexpected status: {status}"


def buildkite_source(
    api_access_token: str,
    organization: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BUILDKITE_ENDPOINTS[endpoint]

    params = _build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BUILDKITE_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted
            # from logs; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_access_token},
            # Buildkite paginates via an RFC 5988 Link header with rel="next".
            "paginator": HeaderLinkPaginator(),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path.format(organization=organization),
                    "params": params,
                    # Buildkite list endpoints return a top-level JSON array; a non-list 200 body
                    # means the response shape changed — fail loud instead of syncing garbage.
                    "data_selector_required": True,
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
        # Persist only when a next page remains; the hook fires AFTER a page is yielded so a crash
        # re-yields the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(BuildkiteResumeConfig(next_url=state["next_url"]))

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
