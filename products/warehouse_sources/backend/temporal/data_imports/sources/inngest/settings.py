from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
    # events (not outbound notifications), so this is a plain config inventory.
    "webhooks": InngestEndpointConfig(
        name="webhooks",
        path="/v1/webhooks",
        primary_keys=["id"],
        pagination="none",
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
