from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Per-region base hostnames for the dbt Cloud Administrative API. Cell-based (e.g.
# https://ab123.us1.dbt.com) and single-tenant deployments use a custom base URL instead.
DBT_REGION_BASE_URLS: dict[str, str] = {
    "us": "https://cloud.getdbt.com",
    "emea": "https://emea.dbt.com",
    "au": "https://au.dbt.com",
}

# dbt Cloud caps limit/offset pagination at 100 rows per request.
DBT_PAGE_LIMIT = 100


@dataclass
class DbtEndpointConfig:
    name: str
    # Path template under {base_url}/api, with an {account_id} placeholder. The API version is part
    # of the path because coverage is split: jobs/runs live on v2, the rest on v3.
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Field to partition by — a stable created-at style field, never one that mutates.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Safety overlap subtracted from the incremental watermark on every run. Runs are cursored on
    # the immutable created_at, but their status/timing fields keep mutating for a while after
    # creation — the lookback re-pulls that recent window so those rows get their final state;
    # merge dedupes them on the primary key.
    incremental_lookback: Optional[timedelta] = None
    description: Optional[str] = None


DBT_ENDPOINTS: dict[str, DbtEndpointConfig] = {
    "accounts": DbtEndpointConfig(
        name="accounts",
        # Not account-scoped: lists every account the token can access.
        path="/v3/accounts/",
        description="dbt platform accounts the API token has access to",
    ),
    "projects": DbtEndpointConfig(
        name="projects",
        path="/v3/accounts/{account_id}/projects/",
        description="dbt projects in the account",
    ),
    "environments": DbtEndpointConfig(
        name="environments",
        path="/v3/accounts/{account_id}/environments/",
        description="Development and deployment environments across the account's projects",
    ),
    "jobs": DbtEndpointConfig(
        name="jobs",
        path="/v2/accounts/{account_id}/jobs/",
        description="Job definitions (scheduled and triggered dbt executions) across the account",
    ),
    "users": DbtEndpointConfig(
        name="users",
        path="/v3/accounts/{account_id}/users/",
        # Listing users needs account-level user permissions many read-only service tokens lack,
        # so leave it deselected by default; the schema picker's permission probe explains why.
        should_sync_default=False,
        description="Users with access to the account. Requires a token with user read permissions",
    ),
    "runs": DbtEndpointConfig(
        name="runs",
        path="/v2/accounts/{account_id}/runs/",
        # The runs list has no server-side time filter, but it supports order_by=-created_at, so
        # incremental syncs walk newest-first and stop once a whole page predates the watermark —
        # only new rows are fetched, unlike a client-side skip cursor.
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_at",
        partition_key="created_at",
        sort_mode="desc",
        incremental_lookback=timedelta(hours=24),
        description="Job run history, including status, timing, and git metadata",
    ),
}

ENDPOINTS = tuple(DBT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DBT_ENDPOINTS.items()
}
