from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Vendor API versions. Inngest serves its REST API under URL-path-versioned prefixes
# (`/v1/...`, `/v2/...`) and the per-environment signing key authenticates both. Every resource
# this source reads lives under a single version — the events walk, cancellations and webhooks are
# v1-only, while environments and the key inventories are v2-only — so their paths are fixed
# regardless of a source's pin. New sources default to v2.
INNGEST_API_VERSION_V1 = "v1"
INNGEST_API_VERSION_V2 = "v2"
INNGEST_SUPPORTED_VERSIONS = (INNGEST_API_VERSION_V1, INNGEST_API_VERSION_V2)
INNGEST_DEFAULT_VERSION = INNGEST_API_VERSION_V2

# Documented max `limit` for the v2 apps, functions, runs and sessions lists.
V2_MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class InngestVersionPath:
    path: str
    pagination: Literal["events_cursor", "v2_cursor", "v2_runs_window", "none"]


@dataclass(frozen=True)
class InngestEndpointConfig:
    name: str
    path: str
    # Primary key columns for the merge upsert. Must be unique table-wide.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-style field to partition by (never a mutable field).
    partition_key: Optional[str] = None
    # How the endpoint pages:
    #   - "events_cursor": the /v1/events walk — `cursor` (last event internal_id) + `limit`,
    #     bounded by an explicit [received_after, received_before] window.
    #   - "v2_cursor": v2 envelope pagination — follow `page.cursor` while `page.hasMore`.
    #   - "v2_runs_window": v2 envelope pagination over a pinned [from, until] queuedAt window,
    #     ordered ascending.
    #   - "none": a single request returning the full (small) list.
    pagination: Literal["events_cursor", "v2_cursor", "v2_runs_window", "none"] = "none"
    # When True, the endpoint fans out over the incremental events walk, fetching
    # GET /v1/events/{internal_id}/runs once per event.
    fan_out_runs_per_event: bool = False
    # v2 parent/child walks: "app_functions" lists each app's functions, "session_key_sessions"
    # lists each session key's sessions, "session_runs" lists each session's runs.
    fan_out: Optional[Literal["app_functions", "session_key_sessions", "session_runs"]] = None
    # `limit` sent on v2 list requests. None keeps the server default.
    page_size: Optional[int] = None
    # Secret-bearing response fields dropped from every row before yielding — key material
    # must never be synced into the warehouse.
    redacted_fields: tuple[str, ...] = ()
    # Per-schema default overlap window re-read on each incremental run (see SourceSchema).
    default_incremental_lookback_seconds: Optional[int] = None
    should_sync_default: bool = True
    # For resources Inngest serves under more than one API version, the path + pagination the
    # source uses per resolved `api_version` pin. Absent → the resource is version-locked to
    # `path` (its only compatible home) and every pin reads it there.
    version_paths: dict[str, InngestVersionPath] = field(default_factory=dict)


# Endpoint catalog. Inngest's REST API lives at api.inngest.com (v1 + v2), authenticated with a
# per-environment signing key (`Authorization: Bearer signkey-...`), which works on both API
# versions; dashboard API keys only cover v2, which is why the source asks for a signing key.
# Branch/custom environments are targeted with the `X-Inngest-Env` header.
#
# Only the event-driven endpoints sync incrementally: GET /v1/events takes `received_after` /
# `received_before` RFC3339 bounds, a genuine server-side filter (and `received_after` defaults to
# only 1 hour ago, so we always pass it explicitly). `function_runs` is discovered by walking the
# events window and fetching each event's runs, so it misses cron- and invoke-triggered runs;
# `runs` lists every run directly from GET /v2/runs with a server-side queuedAt window. The
# remaining endpoints are full-refresh inventories with no server-side timestamp filter.
INNGEST_ENDPOINTS: dict[str, InngestEndpointConfig] = {
    "events": InngestEndpointConfig(
        name="events",
        path="/v1/events",
        # `internal_id` is the ULID Inngest assigns to every received event; the user-supplied
        # `id` field is optional and only unique per sender.
        primary_keys=["internal_id"],
        partition_key="received_at",
        pagination="events_cursor",
        incremental_fields=[
            {
                "label": "received_at",
                "type": IncrementalFieldType.DateTime,
                "field": "received_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "function_runs": InngestEndpointConfig(
        name="function_runs",
        path="/v1/events/{internal_id}/runs",
        primary_keys=["run_id"],
        # `run_started_at` is when the run was scheduled and never changes; `event_received_at`
        # (the injected incremental field) can differ per parent event for batch runs, so it is
        # not safe as a partition key.
        partition_key="run_started_at",
        pagination="events_cursor",
        fan_out_runs_per_event=True,
        # Runs fetched while still Running keep that status until re-pulled; re-read a trailing
        # hour each run so recently-discovered runs get their terminal status. Longer-lived runs
        # only settle on a full refresh.
        default_incremental_lookback_seconds=3600,
        incremental_fields=[
            {
                "label": "event_received_at",
                "type": IncrementalFieldType.DateTime,
                "field": "event_received_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "runs": InngestEndpointConfig(
        name="runs",
        path="/v2/runs",
        # Run IDs are ULIDs, unique across the environment.
        primary_keys=["id"],
        # `queuedAt` is set when the run is enqueued and never changes.
        partition_key="queuedAt",
        pagination="v2_runs_window",
        page_size=V2_MAX_PAGE_SIZE,
        # The window filters on queuedAt, so a run that was still Running when pulled keeps that
        # status until re-read; re-read a trailing hour each run so recent runs settle.
        default_incremental_lookback_seconds=3600,
        incremental_fields=[
            {
                "label": "queuedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "queuedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "functions": InngestEndpointConfig(
        name="functions",
        path="/v2/apps/{app_id}/functions",
        # Function IDs are only documented per app, so the parent app ID is part of the key.
        primary_keys=["app_id", "id"],
        pagination="v2_cursor",
        fan_out="app_functions",
        page_size=V2_MAX_PAGE_SIZE,
    ),
    "cancellations": InngestEndpointConfig(
        name="cancellations",
        path="/v1/cancellations",
        primary_keys=["id"],
        pagination="none",
    ),
    "environments": InngestEndpointConfig(
        name="environments",
        path="/v2/envs",
        primary_keys=["id"],
        pagination="v2_cursor",
    ),
    # Inngest webhooks are inbound intake URLs that transform third-party payloads into Inngest
    # events (not outbound notifications), so this is a plain config inventory. The intake URL is
    # capability-bearing — anyone holding it can submit events that trigger functions — so it is
    # stripped like key material.
    "webhooks": InngestEndpointConfig(
        name="webhooks",
        path="/v1/webhooks",
        primary_keys=["id"],
        pagination="none",
        redacted_fields=("url",),
    ),
    "event_keys": InngestEndpointConfig(
        name="event_keys",
        path="/v2/keys/events",
        primary_keys=["id"],
        pagination="v2_cursor",
        redacted_fields=("key",),
    ),
    "signing_keys": InngestEndpointConfig(
        name="signing_keys",
        path="/v2/keys/signing",
        primary_keys=["id"],
        pagination="v2_cursor",
        redacted_fields=("key",),
    ),
    # AgentKit sessions: a session key names a grouping dimension, a session is one value of it.
    "session_keys": InngestEndpointConfig(
        name="session_keys",
        path="/v2/sessions",
        primary_keys=["id"],
        pagination="v2_cursor",
        page_size=V2_MAX_PAGE_SIZE,
    ),
    "sessions": InngestEndpointConfig(
        name="sessions",
        path="/v2/sessions/{session_key}",
        primary_keys=["session_key", "id"],
        pagination="v2_cursor",
        fan_out="session_key_sessions",
        page_size=V2_MAX_PAGE_SIZE,
    ),
    "session_runs": InngestEndpointConfig(
        name="session_runs",
        path="/v2/sessions/{session_key}/{session_id}/runs",
        # A run can belong to more than one session, so both parents are part of the key.
        primary_keys=["session_key", "session_id", "id"],
        partition_key="queuedAt",
        pagination="v2_cursor",
        fan_out="session_runs",
        page_size=V2_MAX_PAGE_SIZE,
        # One request per session, so it is opt-in.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(INNGEST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INNGEST_ENDPOINTS.items()
}
