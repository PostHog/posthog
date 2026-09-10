from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Amplitude exposes regional deployments. The project's API key + secret key authenticate
# against a single project that lives in one region, so the host is chosen by the `region`
# form field rather than by a user-supplied URL (no SSRF surface — the set is fixed).
AMPLITUDE_HOSTS: dict[str, str] = {
    "us": "https://amplitude.com",
    "eu": "https://analytics.eu.amplitude.com",
}

# The Export API enforces a ~2 hour ingestion latency (events uploaded in the last couple of
# hours may not be queryable yet) and rejects windows longer than 365 days. We page through
# history one day at a time using the hour-granular `start`/`end` params (YYYYMMDDTHH).
EVENTS_EXPORT_LATENCY_HOURS = 2
EVENTS_EXPORT_WINDOW_HOURS = 24
# Bound the first sync to a recent window so an initial backfill of a high-volume project does
# not attempt to pull years of raw events in one run. Subsequent incremental syncs only fetch
# windows newer than the stored cursor.
EVENTS_DEFAULT_LOOKBACK_DAYS = 30

EVENTS_ENDPOINT = "events"
COHORTS_ENDPOINT = "cohorts"
ANNOTATIONS_ENDPOINT = "annotations"


@dataclass
class AmplitudeEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # The Export API (events) returns a zip of gzipped JSON archives rather than a JSON body,
    # so it has no data selector. The Dashboard REST endpoints wrap their list in a JSON key.
    is_export: bool = False
    data_selector: str | None = None
    supports_incremental: bool = False
    supports_append: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Must be a STABLE datetime field (never `updated_at`/`last_seen`) so partitions don't
    # rewrite on every sync.
    partition_key: str | None = None


AMPLITUDE_ENDPOINTS: dict[str, AmplitudeEndpointConfig] = {
    EVENTS_ENDPOINT: AmplitudeEndpointConfig(
        name=EVENTS_ENDPOINT,
        path="/api/2/export",
        primary_keys=["uuid"],
        is_export=True,
        supports_incremental=True,
        supports_append=True,
        # The Export API filters on server upload time, so that is the only correct cursor —
        # an event's `event_time` can be backdated by offline/late clients, but the window we
        # ask for is bounded by when Amplitude received the event.
        incremental_fields=[
            {
                "label": "server_upload_time",
                "type": IncrementalFieldType.DateTime,
                "field": "server_upload_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="event_time",
    ),
    COHORTS_ENDPOINT: AmplitudeEndpointConfig(
        name=COHORTS_ENDPOINT,
        path="/api/3/cohorts",
        primary_keys=["id"],
        data_selector="cohorts",
    ),
    ANNOTATIONS_ENDPOINT: AmplitudeEndpointConfig(
        name=ANNOTATIONS_ENDPOINT,
        path="/api/2/annotations",
        primary_keys=["id"],
        data_selector="data",
    ),
}

ENDPOINTS = tuple(AMPLITUDE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AMPLITUDE_ENDPOINTS.items()
}
