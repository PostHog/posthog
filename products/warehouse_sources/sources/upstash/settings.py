from products.warehouse_sources.sources.sdk import frozen

# The Upstash Developer (management) API. Almost every resource lives under the versioned base.
UPSTASH_API_BASE_URL = "https://api.upstash.com/v2"
# Audit logs are the one exception: they are served from the unversioned host (GET /auditlogs).
UPSTASH_ROOT_BASE_URL = "https://api.upstash.com"


@frozen
class UpstashFanOutParent:
    # Internal resource name for the parent listing, distinct from every public endpoint name.
    name: str
    path: str
    # Parent row field resolved into the child path (`{<id_field>}`) and stamped onto each child row.
    id_field: str
    # The listing returns credentials (vector index / QStash tokens). The rows are never yielded, but
    # the response would still reach HTTP sample capture, so the child endpoint turns capture off.
    carries_secrets: bool = False


_REDIS_DATABASES_PARENT = UpstashFanOutParent(
    name="redis_databases_parent", path="/redis/databases", id_field="database_id"
)
_TEAMS_PARENT = UpstashFanOutParent(name="teams_parent", path="/teams", id_field="team_id")
_VECTOR_INDEXES_PARENT = UpstashFanOutParent(
    name="vector_indexes_parent", path="/vector/index", id_field="id", carries_secrets=True
)
_QSTASH_USERS_PARENT = UpstashFanOutParent(
    name="qstash_users_parent", path="/qstash/users", id_field="id", carries_secrets=True
)


@frozen
class UpstashEndpointConfig:
    name: str
    # Path appended to `base_url`. For fan-out endpoints it is a template carrying `{<parent id_field>}`.
    path: str
    # Composite/primary key columns used to dedupe on merge. Fan-out children include the parent id.
    primary_keys: list[str]
    # Host the path is appended to. Defaults to the versioned base; audit logs override it.
    base_url: str = UPSTASH_API_BASE_URL
    # Fan out over every row of the parent listing, calling `path` once per parent id.
    fan_out_parent: UpstashFanOutParent | None = None
    # Column the parent id is stamped under on each child row. Defaults to the parent's `id_field`.
    parent_id_column: str | None = None
    # Whether the table is selected for sync by default in the wizard.
    should_sync_default: bool = True
    # Response fields carrying credentials/secrets. They are stripped from every row before it reaches
    # the warehouse, and their presence disables HTTP sample capture for the endpoint (the generic
    # scrubber does not redact fields named `token`).
    sensitive_fields: frozenset[str] = frozenset()


# The Upstash management API is full-refresh only: no list endpoint documents pagination, and none
# exposes a server-side created/updated-since filter (probed against the live API — the databases,
# teams, vector index, and auditlogs endpoints accept no query parameters; the stats endpoints take
# only a `period` for their short-window series). Entity volumes are tiny (an account rarely has more
# than dozens of databases/indices), so a full refresh over each small collection is cheap. No
# endpoint is incremental, so none declares incremental fields.
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
        fan_out_parent=_REDIS_DATABASES_PARENT,
    ),
    # GET /v2/teams -> raw array of Team objects (team_id, team_name, copy_cc).
    "teams": UpstashEndpointConfig(
        name="teams",
        path="/teams",
        primary_keys=["team_id"],
    ),
    # GET /v2/teams/{team_id} -> raw array of TeamMember objects (team_id, team_name, member_email,
    # member_role). Fanned out over every team; an email is unique within a team, not across teams.
    "team_members": UpstashEndpointConfig(
        name="team_members",
        path="/teams/{team_id}",
        primary_keys=["team_id", "member_email"],
        fan_out_parent=_TEAMS_PARENT,
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
    # GET /v2/vector/index/{id}/stats -> one VectorStats object per index (daily/monthly query and
    # update counts, bandwidth, storage, cost, latency series). The account-wide /vector/index/stats
    # total carries no id, so the per-index endpoint is fanned out instead, like redis_stats.
    "vector_index_stats": UpstashEndpointConfig(
        name="vector_index_stats",
        path="/vector/index/{id}/stats",
        primary_keys=["index_id"],
        fan_out_parent=_VECTOR_INDEXES_PARENT,
        parent_id_column="index_id",
    ),
    # GET /v2/search -> raw array of SearchIndex objects (plan, region, limits, creation_time).
    # Like vector indexes, `token` and `read_only_token` are index credentials and are stripped.
    "search_indexes": UpstashEndpointConfig(
        name="search_indexes",
        path="/search",
        primary_keys=["id"],
        sensitive_fields=frozenset({"token", "read_only_token"}),
    ),
    # GET /v2/qstash/stats/{id} -> one QStashStats object per QStash user (daily requests, billing,
    # bandwidth, and workflow series). Fanned out over GET /v2/qstash/users.
    "qstash_stats": UpstashEndpointConfig(
        name="qstash_stats",
        path="/qstash/stats/{id}",
        primary_keys=["qstash_user_id"],
        fan_out_parent=_QSTASH_USERS_PARENT,
        parent_id_column="qstash_user_id",
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
