from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class HealthchecksEndpointConfig:
    name: str
    # Path relative to the API base (e.g. "/checks/"). Fan-out child paths carry a
    # `{check_key}` placeholder filled per parent check.
    path: str
    # Top-level key wrapping the list in the JSON envelope ("checks"/"channels"/"pings").
    # None means the endpoint returns a bare JSON array (flips).
    data_key: str | None
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # True only when the API exposes a genuine server-side timestamp filter (flips `start`).
    supports_incremental: bool = False
    # A STABLE datetime field to partition by — never one that mutates on update.
    partition_key: str | None = None
    # Iterate every check and query this endpoint per check, injecting `check_id`.
    fan_out_over_checks: bool = False
    should_sync_default: bool = True


HEALTHCHECKS_ENDPOINTS: dict[str, HealthchecksEndpointConfig] = {
    # All checks and their current config + status. Small, unpaginated, no server-side
    # updated-since filter, so full refresh. No stable creation timestamp is exposed, so no
    # partition key. `id` is synthesized in the transport as uuid (full key) or unique_key
    # (read-only key) so the primary key is stable regardless of API-key type.
    "checks": HealthchecksEndpointConfig(
        name="checks",
        path="/checks/",
        data_key="checks",
        primary_keys=["id"],
    ),
    # Notification integrations (email, sms, webhook, ...). Small, unpaginated, no timestamps.
    "channels": HealthchecksEndpointConfig(
        name="channels",
        path="/channels/",
        data_key="channels",
        primary_keys=["id"],
    ),
    # Up/down status-change history — the analytics-valuable stream. Fanned out per check.
    # The flips endpoint accepts `start=<unix>` (server-side "newer than" filter), so this is
    # genuinely incremental on `timestamp`. `timestamp` is immutable, so it doubles as the
    # partition key. Accepts uuid OR unique_key, so it works with read-only API keys.
    "flips": HealthchecksEndpointConfig(
        name="flips",
        path="/checks/{check_key}/flips/",
        data_key=None,
        primary_keys=["check_id", "timestamp"],
        supports_incremental=True,
        partition_key="timestamp",
        fan_out_over_checks=True,
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Recent execution log, fanned out per check. The API returns only the plan-bounded window
    # (100 free / 1000 paid, newest-first) with no server-side time filter, so full refresh —
    # the table reflects the currently-retained window. `date` is immutable (partition key).
    # `n` (ping number) is monotonic per check, so [check_id, n] is a stable composite key.
    # The pings sub-endpoint only accepts the full uuid, so a read-only key (uuid omitted)
    # cannot sync it; the transport skips such checks with a warning.
    "pings": HealthchecksEndpointConfig(
        name="pings",
        path="/checks/{check_key}/pings/",
        data_key="pings",
        primary_keys=["check_id", "n"],
        partition_key="date",
        fan_out_over_checks=True,
    ),
}

ENDPOINTS = tuple(HEALTHCHECKS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HEALTHCHECKS_ENDPOINTS.items()
}
