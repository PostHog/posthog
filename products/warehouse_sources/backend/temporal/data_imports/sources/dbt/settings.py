from dataclasses import field
from datetime import timedelta
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.dbt.queries import (
    EXPOSURES_QUERY,
    MODEL_HISTORICAL_RUNS_QUERY,
    MODELS_QUERY,
    SEEDS_QUERY,
    SNAPSHOTS_QUERY,
    SOURCES_QUERY,
    TESTS_QUERY,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# dbt Cloud's Administrative API runs two live versions: v3 (the vendor's recommended version) and
# v2 (legacy). There is no v1 — UNVERSIONED_API_VERSION ("v1") is only the framework placeholder
# pre-versioning rows carry. This source already reads every resource from whichever version serves
# it: accounts/projects/environments/users on v3, jobs/runs on v2 (v3 exposes neither jobs/runs nor
# a bare account-detail endpoint for the credential probe). That split is fixed by the vendor, so a
# "v1"- and a "v3"-pinned source issue byte-for-byte identical requests and nothing branches on the
# pin; declaring v3 only makes the source's public version metadata name the API it actually targets.
DBT_API_VERSION_V3 = "v3"
DBT_SUPPORTED_VERSIONS = (UNVERSIONED_API_VERSION, DBT_API_VERSION_V3)
DBT_DEFAULT_VERSION = DBT_API_VERSION_V3

# Per-region base hostnames for the dbt Cloud Administrative API. Cell-based (e.g.
# https://ab123.us1.dbt.com) and single-tenant deployments use a custom base URL instead.
DBT_REGION_BASE_URLS: dict[str, str] = {
    "us": "https://cloud.getdbt.com",
    "emea": "https://emea.dbt.com",
    "au": "https://au.dbt.com",
}

# dbt Cloud caps limit/offset pagination at 100 rows per request.
DBT_PAGE_LIMIT = 100

# The Discovery API (model/test/source state and run history) is a separate GraphQL service on its
# own per-region hostname. Cell-based and single-tenant deployments prefix the account, so those
# users supply the URL directly instead (see the discovery_api_url source field).
DBT_DISCOVERY_REGION_URLS: dict[str, str] = {
    "us": "https://metadata.cloud.getdbt.com/graphql",
    "emea": "https://metadata.emea.dbt.com/graphql",
    "au": "https://metadata.au.dbt.com/graphql",
}

# Discovery API connections accept up to 500 nodes per page; 100 keeps each response small enough
# to stay well inside the documented response-size and query-complexity limits.
DBT_DISCOVERY_PAGE_SIZE = 100

# Runs per model requested from modelHistoricalRuns, matching the count in dbt's own example query.
DBT_MODEL_HISTORICAL_RUN_COUNT = 20


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@frozen
class DbtRunFanoutConfig:
    """A child resource of a run, fetched once per run in the runs list."""

    # Path template under {base_url}/api, with {account_id} and {run_id} placeholders.
    path: str
    # include_related values to ask for on the child call.
    include_related: tuple[str, ...] = ()
    # Key inside the response envelope's `data` object holding the child rows. None means `data`
    # is itself the row list.
    data_selector: Optional[str] = None
    # Set when the child rows are bare strings rather than objects; names the column they land in.
    string_row_field: Optional[str] = None


@frozen
class DbtProjectFanoutConfig:
    """A list resource scoped to a project, walked once per project in the account."""

    # Path template under {base_url}/api, with {account_id} and {project_id} placeholders.
    path: str


@frozen
class DbtDiscoveryConfig:
    """An endpoint served by the Discovery API (GraphQL) instead of the Admin API."""

    query: str
    # AppliedState field the rows come from; also the connection key in the response.
    applied_field: str
    # modelHistoricalRuns takes one model at a time, so its rows come from a second walk over the
    # environment's models rather than from a paginated connection.
    per_model: bool = False


@frozen
class DbtEndpointConfig:
    name: str
    # Path template under {base_url}/api, with an {account_id} placeholder. The API version is part
    # of the path because coverage is split: jobs/runs/licenses live on v2, the rest on v3. None
    # for endpoints that are not a top-level Admin API list (fan-outs and Discovery API tables).
    path: Optional[str] = None
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
    # Set when rows come from a child resource fetched once per run instead of a list endpoint.
    run_fanout: Optional[DbtRunFanoutConfig] = None
    # Set when rows come from a list resource fetched once per project instead of an account list.
    project_fanout: Optional[DbtProjectFanoutConfig] = None
    # Set when the response holds one object keyed by a type name rather than one row per item;
    # names the column each key lands in, and the key's object becomes that row.
    keyed_row_field: Optional[str] = None
    # Set when rows come from the Discovery API instead of the Admin API.
    discovery: Optional[DbtDiscoveryConfig] = None
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
    "run_steps": DbtEndpointConfig(
        name="run_steps",
        # run_steps is only an include_related value on the run-detail route, not on the runs list,
        # so each run in the window costs one extra request.
        run_fanout=DbtRunFanoutConfig(
            path="/v2/accounts/{account_id}/runs/{run_id}/",
            include_related=("run_steps",),
            data_selector="run_steps",
        ),
        # A step is identified by its position in its run; the nested step objects carry no id.
        primary_keys=["run_id", "index"],
        incremental_fields=[_datetime_incremental_field("run_created_at")],
        default_incremental_field="run_created_at",
        partition_key="run_created_at",
        sort_mode="desc",
        incremental_lookback=timedelta(hours=24),
        should_sync_default=False,
        description="Individual steps within each job run, with per-step command, status and logs. Costs one extra request per run",
    ),
    "run_artifacts": DbtEndpointConfig(
        name="run_artifacts",
        run_fanout=DbtRunFanoutConfig(
            path="/v2/accounts/{account_id}/runs/{run_id}/artifacts/",
            string_row_field="path",
        ),
        primary_keys=["run_id", "path"],
        incremental_fields=[_datetime_incremental_field("run_created_at")],
        default_incremental_field="run_created_at",
        partition_key="run_created_at",
        sort_mode="desc",
        incremental_lookback=timedelta(hours=24),
        should_sync_default=False,
        description="Which artifact files each job run produced. Costs one extra request per run",
    ),
    "audit_logs": DbtEndpointConfig(
        name="audit_logs",
        path="/v3/accounts/{account_id}/audit-logs/",
        # The endpoint documents no timestamp filter and no order_by, so there is no way to stop
        # a walk early, so this table is full refresh only.
        should_sync_default=False,
        description="Account audit events: who changed jobs, environments and permissions, and when. Requires an Enterprise plan",
    ),
    "repositories": DbtEndpointConfig(
        name="repositories",
        # The account-level v2 list is deprecated; v3 only lists repositories per project.
        project_fanout=DbtProjectFanoutConfig(path="/v3/accounts/{account_id}/projects/{project_id}/repositories/"),
        description="The git repository behind each project, with its provider and clone strategy. Costs one extra request per project",
    ),
    "connections": DbtEndpointConfig(
        name="connections",
        path="/v3/accounts/{account_id}/connections/",
        description="Data platform connections in the account, with the adapter each one uses",
    ),
    "groups": DbtEndpointConfig(
        name="groups",
        path="/v3/accounts/{account_id}/groups/",
        # Like users, listing groups needs account-level permissions many read-only tokens lack.
        should_sync_default=False,
        description="Permission groups in the account, with their member count, SSO mappings and the permission sets they grant",
    ),
    "license_allocations": DbtEndpointConfig(
        name="license_allocations",
        path="/v2/accounts/{account_id}/licenses/",
        keyed_row_field="license_type",
        primary_keys=["license_type"],
        should_sync_default=False,
        description="Seat totals and usage for each license type in the account. Requires a token that can read the account's licenses",
    ),
    "models": DbtEndpointConfig(
        name="models",
        discovery=DbtDiscoveryConfig(query=MODELS_QUERY, applied_field="models"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Current state of every model in each deployment environment, including its last run result. Needs a token with Discovery API access",
    ),
    "tests": DbtEndpointConfig(
        name="tests",
        discovery=DbtDiscoveryConfig(query=TESTS_QUERY, applied_field="tests"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Current state of every data test, including its last known result. Needs a token with Discovery API access",
    ),
    "sources": DbtEndpointConfig(
        name="sources",
        discovery=DbtDiscoveryConfig(query=SOURCES_QUERY, applied_field="sources"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Current state of every source, including freshness checks. Needs a token with Discovery API access",
    ),
    "snapshots": DbtEndpointConfig(
        name="snapshots",
        discovery=DbtDiscoveryConfig(query=SNAPSHOTS_QUERY, applied_field="snapshots"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Current state of every snapshot, including its last run result. Needs a token with Discovery API access",
    ),
    "seeds": DbtEndpointConfig(
        name="seeds",
        discovery=DbtDiscoveryConfig(query=SEEDS_QUERY, applied_field="seeds"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Current state of every seed, including its last run result. Needs a token with Discovery API access",
    ),
    "exposures": DbtEndpointConfig(
        name="exposures",
        discovery=DbtDiscoveryConfig(query=EXPOSURES_QUERY, applied_field="exposures"),
        primary_keys=["environmentId", "uniqueId"],
        should_sync_default=False,
        description="Downstream exposures declared in each project, with their owner and maturity. Needs a token with Discovery API access",
    ),
    "model_historical_runs": DbtEndpointConfig(
        name="model_historical_runs",
        discovery=DbtDiscoveryConfig(
            query=MODEL_HISTORICAL_RUNS_QUERY, applied_field="modelHistoricalRuns", per_model=True
        ),
        primary_keys=["environmentId", "uniqueId", "runId"],
        should_sync_default=False,
        description=(
            "Per-model execution history: build time and status for each of a model's recent runs. "
            "Costs one request per model, and the Discovery API only retains two months"
        ),
    ),
}

ENDPOINTS = tuple(DBT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DBT_ENDPOINTS.items()
}
