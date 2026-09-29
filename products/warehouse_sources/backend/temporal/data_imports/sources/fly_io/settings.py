from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FlyIoFanoutConfig:
    # Schema name of the endpoint whose rows drive this one.
    parent: str
    # Child path placeholder -> the parent row field bound to it.
    path_params: dict[str, str]
    # Parent row field -> the column each child row carries it under.
    parent_fields: dict[str, str]


@dataclass
class FlyIoEndpointConfig:
    name: str
    # Path template relative to the API base. `{org_slug}` is substituted with the configured
    # organization for the org-scoped endpoints; the apps endpoint takes org_slug as a query
    # param instead (see `_endpoint_path`/`_endpoint_params` in fly_io.py). A fan-out child's
    # placeholders are bound per parent row instead (see `fanout`).
    path: str
    # Body key the list of rows lives under (e.g. {"apps": [...]}, {"machines": [...]}).
    # None when the endpoint returns a bare array.
    response_data_path: Optional[str]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. None disables partitioning —
    # Fly.io app objects carry no timestamp at all.
    partition_key: Optional[str] = None
    # True when the endpoint returns a `next_cursor` and accepts a `cursor` query param.
    paginated: bool = False
    # True when the endpoint scopes to an organization through an `org_slug` query param rather
    # than through the path. The platform-wide endpoints take neither.
    org_slug_param: bool = False
    # True when the stream's HTTP traffic can carry deployment secrets, either in its own rows
    # or in its fan-out parent's. Such a stream is excluded from HTTP sample capture so secrets
    # never reach the sample-capture pipeline.
    redact_secrets: bool = False
    # Row key holding a machine config (env vars, per-process env, inline file contents). Such a
    # field is reduced to a safe operational allowlist before the row is yielded, so secrets
    # never reach the warehouse.
    secret_config_field: Optional[str] = None
    # Set when the endpoint only exists per parent resource and has to be fanned out.
    fanout: Optional[FlyIoFanoutConfig] = None


# Fly.io streams. We use the org-level aggregate endpoints for machines and volumes
# (GET /orgs/{org_slug}/machines, GET /orgs/{org_slug}/volumes) rather than fanning out
# per app: each returns every resource in the org in one cursor-paginated call and stamps
# `app_name` onto each row, so it carries the app context without an extra request per app
# (which also stays well within Fly.io's per-action rate limits for orgs with many apps).
FLY_IO_ENDPOINTS: dict[str, FlyIoEndpointConfig] = {
    "apps": FlyIoEndpointConfig(
        name="apps",
        path="/apps",
        response_data_path="apps",
        # App objects have no created_at/updated_at, so datetime partitioning isn't possible.
        partition_key=None,
        paginated=False,
        org_slug_param=True,
    ),
    "machines": FlyIoEndpointConfig(
        name="machines",
        path="/orgs/{org_slug}/machines",
        response_data_path="machines",
        partition_key="created_at",
        paginated=True,
        redact_secrets=True,
        secret_config_field="config",
    ),
    "volumes": FlyIoEndpointConfig(
        name="volumes",
        path="/orgs/{org_slug}/volumes",
        response_data_path="volumes",
        partition_key="created_at",
        paginated=True,
    ),
    "regions": FlyIoEndpointConfig(
        name="regions",
        path="/platform/regions",
        response_data_path="regions",
        primary_keys=["code"],
        # Regions are a static lookup with no timestamps.
        partition_key=None,
        paginated=False,
    ),
    "machine_events": FlyIoEndpointConfig(
        name="machine_events",
        path="/apps/{app_name}/machines/{machine_id}/events",
        response_data_path=None,
        # Nothing documents the event id as globally unique, so key on the machine too.
        primary_keys=["machine_id", "id"],
        # The only time field is `timestamp`, epoch milliseconds rather than the RFC 3339 string
        # datetime partitioning needs.
        partition_key=None,
        paginated=False,
        # Event rows carry no secrets, but the machines listing that drives the fan-out does.
        redact_secrets=True,
        fanout=FlyIoFanoutConfig(
            parent="machines",
            path_params={"app_name": "app_name", "machine_id": "id"},
            parent_fields={"app_name": "app_name", "id": "machine_id"},
        ),
    ),
    "machine_versions": FlyIoEndpointConfig(
        name="machine_versions",
        path="/apps/{app_name}/machines/{machine_id}/versions",
        response_data_path=None,
        # A version row carries no id — `version` identifies the config within its machine.
        primary_keys=["machine_id", "version"],
        # Version rows carry no timestamp.
        partition_key=None,
        paginated=False,
        redact_secrets=True,
        secret_config_field="user_config",
        fanout=FlyIoFanoutConfig(
            parent="machines",
            path_params={"app_name": "app_name", "machine_id": "id"},
            parent_fields={"app_name": "app_name", "id": "machine_id"},
        ),
    ),
    "volume_snapshots": FlyIoEndpointConfig(
        name="volume_snapshots",
        path="/apps/{app_name}/volumes/{volume_id}/snapshots",
        response_data_path=None,
        # Nothing documents the snapshot id as globally unique, so key on the volume too.
        primary_keys=["volume_id", "id"],
        partition_key="created_at",
        paginated=False,
        fanout=FlyIoFanoutConfig(
            parent="volumes",
            path_params={"app_name": "app_name", "volume_id": "id"},
            parent_fields={"app_name": "app_name", "id": "volume_id"},
        ),
    ),
}

ENDPOINTS = tuple(FLY_IO_ENDPOINTS.keys())

# Fly.io exposes no verified server-side timestamp filter for these streams. The org
# machines/volumes endpoints document an `updated_after` param, but the API states `cursor`
# takes precedence over it (so it can only bound the first page) and we could not curl-verify
# it actually filters. So every stream is full-refresh only and advertises no incremental
# fields. Resource counts per org are small, so a full refresh each sync is cheap.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FLY_IO_ENDPOINTS}
