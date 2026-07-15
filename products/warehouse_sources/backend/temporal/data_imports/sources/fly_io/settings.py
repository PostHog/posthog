from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class FlyIoEndpointConfig:
    name: str
    # Path template relative to the API base. `{org_slug}` is substituted with the configured
    # organization for the org-scoped endpoints; the apps endpoint takes org_slug as a query
    # param instead (see `_build_url` in fly_io.py).
    path: str
    # Body key the list of rows lives under (e.g. {"apps": [...]}, {"machines": [...]}).
    response_data_path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp used for datetime partitioning. None disables partitioning —
    # Fly.io app objects carry no timestamp at all.
    partition_key: Optional[str] = None
    # True when the endpoint returns a `next_cursor` and accepts a `cursor` query param.
    paginated: bool = False
    # True when rows can embed deployment secrets (a machine's `config` carries env vars,
    # per-process env, and inline file contents). Such a stream is reduced to a safe
    # operational allowlist before it's yielded and excluded from HTTP sample capture, so
    # secrets never reach the warehouse or the sample-capture pipeline.
    redact_secrets: bool = False


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
    ),
    "machines": FlyIoEndpointConfig(
        name="machines",
        path="/orgs/{org_slug}/machines",
        response_data_path="machines",
        partition_key="created_at",
        paginated=True,
        redact_secrets=True,
    ),
    "volumes": FlyIoEndpointConfig(
        name="volumes",
        path="/orgs/{org_slug}/volumes",
        response_data_path="volumes",
        partition_key="created_at",
        paginated=True,
    ),
}

ENDPOINTS = tuple(FLY_IO_ENDPOINTS.keys())

# Fly.io exposes no verified server-side timestamp filter for these streams. The org
# machines/volumes endpoints document an `updated_after` param, but the API states `cursor`
# takes precedence over it (so it can only bound the first page) and we could not curl-verify
# it actually filters. So every stream is full-refresh only and advertises no incremental
# fields. Resource counts per org are small, so a full refresh each sync is cheap.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FLY_IO_ENDPOINTS}
