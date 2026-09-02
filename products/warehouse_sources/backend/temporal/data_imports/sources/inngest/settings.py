from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Vendor API versions. Inngest serves its REST API under URL-path-versioned prefixes
# (`/v1/...`, `/v2/...`) and the per-environment signing key authenticates both. Most resources
# live under a single version — the events walk and cancellations are v1-only, while environments
# and the key inventories are v2-only — so their paths are fixed regardless of a source's pin.
# Webhooks is served under both, so a source's pin selects which inventory it reads (see
# `version_paths` below). New sources default to v2.
INNGEST_API_VERSION_V1 = "v1"
INNGEST_API_VERSION_V2 = "v2"
INNGEST_SUPPORTED_VERSIONS = (INNGEST_API_VERSION_V1, INNGEST_API_VERSION_V2)
INNGEST_DEFAULT_VERSION = INNGEST_API_VERSION_V2


@dataclass(frozen=True)
class InngestVersionPath:
    path: str
    pagination: Literal["events_cursor", "v2_cursor", "none"]


@dataclass
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
    #   - "none": a single request returning the full (small) list.
    pagination: Literal["events_cursor", "v2_cursor", "none"] = "none"
    # When True, the endpoint fans out over the incremental events walk, fetching
    # GET /v1/events/{internal_id}/runs once per event.
    fan_out_runs_per_event: bool = False
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
# only 1 hour ago, so we always pass it explicitly). Function runs have no list endpoint of their
# own — they are discovered by walking the events window and fetching each event's runs. The
# remaining endpoints are small full-refresh inventories with no server-side timestamp filter.
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
        # Webhooks is the one resource this source reads that Inngest serves under both versions.
        # A v2-pinned source reads the v2 inventory (cursor envelope) to stay consistent with its
        # other v2-native reads; v1 pins keep the original `/v1/webhooks` list path. The v2
        # envelope could not be curl-verified without credentials, but `_get_v2_list_rows`
        # degrades to a single page when the response carries no `page` object.
        version_paths={
            INNGEST_API_VERSION_V2: InngestVersionPath(path="/v2/webhooks", pagination="v2_cursor"),
        },
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
}

ENDPOINTS = tuple(INNGEST_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INNGEST_ENDPOINTS.items()
}
