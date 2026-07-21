from dataclasses import dataclass

# The Upstash Developer (management) API. Almost every resource lives under the versioned base.
UPSTASH_API_BASE_URL = "https://api.upstash.com/v2"
# Audit logs are the one exception: they are served from the unversioned host (GET /auditlogs).
UPSTASH_ROOT_BASE_URL = "https://api.upstash.com"


@dataclass
class UpstashEndpointConfig:
    name: str
    # Path appended to `base_url`. For fan-out endpoints it is a template carrying `{database_id}`.
    path: str
    # Composite/primary key columns used to dedupe on merge. Fan-out children include the parent id.
    primary_keys: list[str]
    # Host the path is appended to. Defaults to the versioned base; audit logs override it.
    base_url: str = UPSTASH_API_BASE_URL
    # Fan out over every Redis database id, calling `path.format(database_id=...)` once per database.
    fan_out_over_databases: bool = False
    # Whether the table is selected for sync by default in the wizard.
    should_sync_default: bool = True
    # Response fields carrying credentials/secrets. They are stripped from every row before it reaches
    # the warehouse, and their presence disables HTTP sample capture for the endpoint (the generic
    # scrubber does not redact fields named `token`).
    sensitive_fields: frozenset[str] = frozenset()


# The Upstash management API is full-refresh only: no list endpoint documents pagination, and none
# exposes a server-side created/updated-since filter (probed against the live API — the databases,
# teams, vector index, and auditlogs endpoints accept no query parameters). Entity volumes are tiny
# (an account rarely has more than dozens of databases/indices), so a full refresh over each small
# collection is cheap. No endpoint is incremental, so none declares incremental fields.
UPSTASH_ENDPOINTS: dict[str, UpstashEndpointConfig] = {
    # GET /v2/redis/databases -> raw array of Database objects (config, plan, state, creation_time).
    "redis_databases": UpstashEndpointConfig(
        name="redis_databases",
        path="/redis/databases",
        primary_keys=["database_id"],
    ),
    # GET /v2/redis/stats/{id} -> one DatabaseStats object per database (daily/monthly usage, billing,
    # bandwidth, storage, latency percentiles, cache hits/misses as {x, y} time series). Fanned out
    # over every database id; each row carries its `database_id` so the key is unique table-wide.
    "redis_stats": UpstashEndpointConfig(
        name="redis_stats",
        path="/redis/stats/{database_id}",
        primary_keys=["database_id"],
        fan_out_over_databases=True,
    ),
    # GET /v2/teams -> raw array of Team objects (team_id, team_name, copy_cc).
    "teams": UpstashEndpointConfig(
        name="teams",
        path="/teams",
        primary_keys=["team_id"],
    ),
    # GET /v2/vector/index -> raw array of VectorIndex objects (config, plan, limits, creation_time).
    # `token` and `read_only_token` are write-capable index credentials; strip them so warehouse
    # readers can't retrieve them, and keep the whole response out of HTTP sample capture.
    "vector_indexes": UpstashEndpointConfig(
        name="vector_indexes",
        path="/vector/index",
        primary_keys=["id"],
        sensitive_fields=frozenset({"token", "read_only_token"}),
    ),
    # GET /auditlogs (unversioned host) -> raw array of AuditLog objects (actor, action, entity,
    # timestamp, ip). No time-range or pagination params documented, so it is full refresh.
    "audit_logs": UpstashEndpointConfig(
        name="audit_logs",
        path="/auditlogs",
        primary_keys=["log_id"],
        base_url=UPSTASH_ROOT_BASE_URL,
    ),
}

ENDPOINTS = tuple(UPSTASH_ENDPOINTS.keys())
