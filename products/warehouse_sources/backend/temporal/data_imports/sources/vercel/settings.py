from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class VercelEndpointConfig:
    name: str
    # Versioned path on https://api.vercel.com (Vercel pins each resource to its own API version).
    path: str
    # Key in the JSON response body that holds the list of rows (e.g. {"deployments": [...]}).
    # Empty for endpoints that don't return the shared list-envelope shape (e.g. billing charges,
    # which streams JSONL — see `is_focus_billing`).
    response_data_key: str
    primary_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that lower-bounds results by creation time (Unix ms). Only set where Vercel
    # documents a genuine server-side time filter — None means full refresh for this endpoint.
    since_param: Optional[str] = None
    # Whether `since`/`until` must be sent as ISO 8601 UTC strings rather than raw Unix-ms
    # integers. Vercel's OpenAPI spec types since/until as numbers (e.g. 1540095775941) for
    # deployments, domains, aliases, and teams, but as strings (e.g. "2019-12-08T10:00:38.976Z")
    # for events — sending events a raw ms integer gets rejected with a 400.
    since_until_as_iso: bool = False
    # Team-owned resources require ?teamId=<id> on each request. Endpoints that list resources
    # visible to the token itself (e.g. /v2/teams) are not team-scoped.
    team_scoped: bool = True
    # Whether the schema picker offers incremental (merge) and append sync for this endpoint.
    # Kept explicit per endpoint because billing supports incremental merge but not append.
    supports_incremental: bool = False
    supports_append: bool = False
    # Stable datetime column to partition the Delta table on (never changes once emitted). None
    # leaves the table unpartitioned.
    partition_key: Optional[str] = None
    # Per-schema default for the incremental overlap re-read window (seconds). The pipeline shifts
    # the stored watermark back by this on each incremental run so restated rows get re-read and
    # merged. Only meaningful for incremental endpoints.
    default_incremental_lookback_seconds: Optional[int] = None
    # Billing charges endpoint: streams FOCUS v1.3 records as newline-delimited JSON over a
    # `from`/`to` date window instead of the cursor-paginated list envelope every other endpoint
    # uses. Routed through its own transport path in vercel.py.
    is_focus_billing: bool = False
    # Field holding the row's creation timestamp (Unix ms) for endpoints that return rows but no
    # `pagination` envelope. The transport pages those by feeding the oldest value on a page back
    # as the next `until`. None means the endpoint carries the envelope and pages from
    # `pagination.next`.
    cursor_from_field: Optional[str] = None
    # Static query params this endpoint needs on every request, merged over the shared ones.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fan-out: this endpoint is a child fetched once per row of `fan_out_parent`. `path` carries a
    # `{fan_out_path_param}` placeholder filled from each parent row's `fan_out_parent_field`. Fan-out
    # endpoints are full refresh only (Vercel documents no server-side time filter on them) and
    # non-resumable: a re-run re-fans over every parent and the pipeline's full-refresh replace
    # rewrites the table. None means this is a flat top-level list handled by the paginating transport.
    fan_out_parent: Optional[str] = None
    fan_out_path_param: Optional[str] = None
    fan_out_parent_field: str = "uid"


# Charges get restated after they first post (usage finalization, plus adjustments, credits, and tax
# that land later in the billing cycle). Each incremental run re-reads roughly the last billing cycle
# so those restatements are re-pulled; merge dedupes the overlap on the synthetic charge id. 35 days
# covers a monthly cycle plus a few days of settling.
BILLING_LOOKBACK_SECONDS = 60 * 60 * 24 * 35


# The cursor list endpoints below share one pagination model: the response carries a `pagination`
# object with `count`, `next`, and `prev` Unix-ms timestamps; the next page is requested by passing
# the `next` value back as the `until` query param. Rows arrive newest-first (descending by creation
# time), so those SourceResponses are sort_mode="desc". billing_charges is the exception — it uses a
# date-window JSONL transport and yields ascending (see vercel.py).
VERCEL_ENDPOINTS: dict[str, VercelEndpointConfig] = {
    "deployments": VercelEndpointConfig(
        name="deployments",
        path="/v6/deployments",
        response_data_key="deployments",
        primary_key="uid",
        # /v6/deployments documents `since`/`until` (Unix ms) as a server-side filter on the
        # deployment creation time. `created` is an immutable epoch-ms integer, so it is both the
        # incremental cursor and a stable ordering key.
        since_param="since",
        supports_incremental=True,
        supports_append=True,
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.Integer,
                "field": "created",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # Team activity stream: every action taken on the team, across ~600 event types (deployments,
    # projects, env vars, domains, aliases, certs, flags, firewall config, access groups). The
    # resource tables above hold current state; this one holds the transitions between them, which
    # is what deployment frequency, change-failure rate, and config audit trails are built from.
    "events": VercelEndpointConfig(
        name="events",
        path="/v3/events",
        response_data_key="events",
        primary_key="id",
        # /v3/events documents `since`/`until` (Unix ms) as a server-side filter on event creation
        # time, so this is genuinely incremental rather than a client-side skip. `createdAt` is
        # immutable, making it both the incremental cursor and the pagination cursor.
        since_param="since",
        since_until_as_iso=True,
        supports_incremental=True,
        supports_append=True,
        # Unlike the resource endpoints this one returns no `pagination` envelope, so pages are
        # walked from the oldest `createdAt` on each page.
        cursor_from_field="createdAt",
        # Without this the response carries only the event's summary text, not the entity it acted
        # on. The payload shape varies per event type; the pipeline serializes it to a JSON string
        # column, so the variation doesn't drift the Arrow schema.
        extra_params={"withPayload": "true"},
        # Deliberately left unpartitioned. `createdAt` is Unix *milliseconds*, and the datetime
        # partition mode feeds an int straight to `datetime.fromtimestamp()`, which reads it as
        # seconds and raises for any ms value. Same reason `deployments.created` is unpartitioned.
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.Integer,
                "field": "createdAt",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # The endpoints below are full refresh only: Vercel's public docs describe the `pagination`
    # cursor for them but do not document a server-side creation-time filter, and we have no API
    # credentials to curl-verify one. Marking them incremental would re-page the whole resource
    # every sync at the same API cost as a full refresh, so we ship full refresh until a filter is
    # confirmed against the live API.
    "projects": VercelEndpointConfig(
        name="projects",
        path="/v9/projects",
        response_data_key="projects",
        primary_key="id",
    ),
    "teams": VercelEndpointConfig(
        name="teams",
        path="/v2/teams",
        response_data_key="teams",
        primary_key="id",
        team_scoped=False,
    ),
    "domains": VercelEndpointConfig(
        name="domains",
        path="/v5/domains",
        response_data_key="domains",
        primary_key="id",
    ),
    "aliases": VercelEndpointConfig(
        name="aliases",
        path="/v4/aliases",
        response_data_key="aliases",
        primary_key="uid",
    ),
    # First fan-out endpoint in this source: one GET /v2/deployments/{deploymentId}/check-runs per
    # deployment already synced by the `deployments` table. Check runs are the structured pass/fail
    # gates (build checks, CI integrations) that ran against a deployment, each with its own status,
    # so they answer *which* gate failed where the deployment's own `state` only says *that* it did.
    # The response is {"runs": [...]} with no pagination envelope and no documented server-side time
    # filter, so it's full refresh. Every run row already carries `deploymentId`, so no parent field
    # is injected. `createdAt`/`updatedAt` are Unix ms, so this stays unpartitioned like `events` and
    # `deployments` (the datetime partitioner reads a raw int as seconds and raises on a ms value).
    "check_runs": VercelEndpointConfig(
        name="check_runs",
        path="/v2/deployments/{deploymentId}/check-runs",
        response_data_key="runs",
        primary_key="id",
        fan_out_parent="deployments",
        fan_out_path_param="deploymentId",
        fan_out_parent_field="uid",
    ),
    # Team billing usage & cost, in the FOCUS v1.3 open cost-and-usage standard. Streamed as JSONL
    # over a `from`/`to` window at 1-day granularity. FOCUS records carry no natural id, so the
    # transport synthesizes a stable `id` from the charge period plus its billing dimensions (see
    # vercel.py) — merge updates a charge in place as it gets restated. Incremental (merge) only:
    # append would materialize a duplicate every time a restated charge is re-read.
    "billing_charges": VercelEndpointConfig(
        name="billing_charges",
        path="/v1/billing/charges",
        response_data_key="",  # not a list-envelope response; rows stream as JSONL
        primary_key="id",  # synthesized in vercel.py from the charge's identity/dimension fields
        is_focus_billing=True,
        supports_incremental=True,
        supports_append=False,
        partition_key="charge_period_start",
        default_incremental_lookback_seconds=BILLING_LOOKBACK_SECONDS,
        incremental_fields=[
            {
                "label": "charge_period_start",
                "type": IncrementalFieldType.DateTime,
                "field": "charge_period_start",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(VERCEL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VERCEL_ENDPOINTS.items()
}
