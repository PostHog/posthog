from datetime import UTC, date, datetime
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.eppo.settings import (
    INCREMENTAL_QUERY_PARAM,
    PAGE_LIMIT,
    PAGINATED_ENDPOINTS,
    PARTITION_KEYS,
    PRIMARY_KEYS,
)

BASE_URL = "https://eppo.cloud/api/v1"

# Path + static (non-pagination) params per endpoint. Every response is a bare JSON array, so
# no `data_selector` override is needed (the framework default `"$"` selects the array root).
_ENDPOINT_PATHS: dict[str, str] = {
    "Experiments": "/experiments",
    "Metrics": "/metrics",
    "MetricCollections": "/metrics/collections",
    "FeatureFlags": "/feature-flags",
    "Bandits": "/bandits",
    "Holdouts": "/holdouts",
    "Teams": "/teams",
    "Tags": "/tags",
    "Audiences": "/audiences",
    "Environments": "/environments",
}

_ENDPOINT_STATIC_PARAMS: dict[str, dict[str, Any]] = {
    # Archived flags/teams are excluded by default; pull the full history instead.
    "FeatureFlags": {"include_archived": "true"},
    "Teams": {"include_archived": "true"},
    "Audiences": {"status": "all"},
}


def _format_since(value: Any) -> str:
    """Format an incremental cursor as the ISO 8601 UTC string Eppo's `_since` filters expect."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_params(
    endpoint: str,
    incremental_field: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(_ENDPOINT_STATIC_PARAMS.get(endpoint, {}))

    query_param = INCREMENTAL_QUERY_PARAM.get(incremental_field or "")
    if should_use_incremental_field and query_param and db_incremental_field_last_value is not None:
        params[query_param] = _format_since(db_incremental_field_last_value)

    return params


def _get_resource(
    endpoint: str,
    incremental_field: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    params = _build_params(endpoint, incremental_field, should_use_incremental_field, db_incremental_field_last_value)

    if endpoint in PAGINATED_ENDPOINTS:
        params["limit"] = PAGE_LIMIT

    return {
        "name": endpoint,
        "table_name": endpoint,
        "write_disposition": "merge" if should_use_incremental_field else "replace",
        "endpoint": {
            "path": _ENDPOINT_PATHS[endpoint],
            "params": params,
        },
        "table_format": "delta",
    }


def eppo_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    incremental_field: Optional[str],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    paginator: PaginatorConfig = (
        {"type": "offset", "limit": PAGE_LIMIT, "total_path": None}
        if endpoint in PAGINATED_ENDPOINTS
        else "single_page"
    )

    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": "X-Eppo-Token",
                "location": "header",
            },
            "paginator": paginator,
            # Pin every request (including paginator next-page links) to the Eppo origin and never
            # follow redirects, so the `X-Eppo-Token` credential can't be replayed off-host.
            "allowed_hosts": [],
            "allow_redirects": False,
        },
        "resources": [
            _get_resource(endpoint, incremental_field, should_use_incremental_field, db_incremental_field_last_value)
        ],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value if should_use_incremental_field else None,
    )

    partition_key = PARTITION_KEYS.get(endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe the experiments list endpoint to confirm the API key is genuine."""
    return validate_via_probe(
        # `allow_redirects=False` pins the credential to the validated Eppo host, so a redirect
        # from the probe endpoint can't replay `X-Eppo-Token` to an attacker-controlled origin.
        lambda: make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        f"{BASE_URL}/experiments?limit=1",
        headers={"X-Eppo-Token": api_key},
    )
