from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Pendo hosts each subscription in a region-specific data center and the integration key is
# region-scoped, so the base URL has to match where the subscription lives.
# https://support.pendo.io/hc/en-us/articles/22832528657179-Global-data-hosting
PENDO_REGION_BASE_URLS: dict[str, str] = {
    "us": "https://app.pendo.io",
    "us1": "https://us1.app.pendo.io",
    "eu": "https://app.eu.pendo.io",
    "jp": "https://app.jpn.pendo.io",
    "au": "https://app.au.pendo.io",
}

DEFAULT_REGION = "us"

# How many days of events a full refresh or a first incremental sync reads.
EVENTS_DEFAULT_LOOKBACK_DAYS = 90


@frozen
class PendoEndpointConfig:
    name: str
    primary_keys: list[str]
    # GET list endpoints (feature/page/guide/tracktype/report) set `path`; aggregation endpoints
    # (visitors/accounts/groups) set `aggregation_source` and POST to /api/v1/aggregation. Event
    # endpoints set `event_source` and POST a day-windowed `timeSeries` to the same endpoint.
    path: Optional[str] = None
    aggregation_source: Optional[str] = None
    event_source: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # App-scoped objects and events only cover the default app unless the request asks for every
    # app. Reports and survey responses are not app-scoped and document no such parameter.
    all_apps: bool = True
    # Grouped event sources return buckets with no id of their own. Ungrouped sources, such as
    # survey responses, return one row per record with a Pendo `id`.
    grouped_events: bool = True

    @property
    def is_aggregation(self) -> bool:
        return self.aggregation_source is not None

    @property
    def is_events(self) -> bool:
        return self.event_source is not None


# Event rows are daily buckets keyed by `day`, the bucket's local midnight in epoch milliseconds.
DAY_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "day",
        "type": IncrementalFieldType.Integer,
        "field": "day",
        "field_type": IncrementalFieldType.Integer,
    }
]

SURVEY_RESPONSE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "lastUpdatedAt",
        "type": IncrementalFieldType.Integer,
        "field": "lastUpdatedAt",
        "field_type": IncrementalFieldType.Integer,
    }
]

# Object and visitor/account endpoints are full refresh: Pendo's list endpoints expose no
# server-side timestamp filter, and the aggregation endpoint's time filters only apply to event
# sources. A client-side cursor would still read every row each run, so it would not be a
# genuine incremental sync. Event sources do take a `timeSeries` range, so they sync incrementally.
PENDO_ENDPOINTS: dict[str, PendoEndpointConfig] = {
    "features": PendoEndpointConfig(name="features", path="/api/v1/feature", primary_keys=["id"]),
    "pages": PendoEndpointConfig(name="pages", path="/api/v1/page", primary_keys=["id"]),
    "guides": PendoEndpointConfig(name="guides", path="/api/v1/guide", primary_keys=["id"]),
    "track_types": PendoEndpointConfig(name="track_types", path="/api/v1/tracktype", primary_keys=["id"]),
    # Only the report definitions: each report's results.json has its own column set, and the
    # rows re-project the visitors and accounts tables.
    "reports": PendoEndpointConfig(name="reports", path="/api/v1/report", primary_keys=["id"], all_apps=False),
    "visitors": PendoEndpointConfig(name="visitors", aggregation_source="visitors", primary_keys=["visitorId"]),
    "accounts": PendoEndpointConfig(name="accounts", aggregation_source="accounts", primary_keys=["accountId"]),
    # Pendo's `groups` source holds product areas.
    "product_areas": PendoEndpointConfig(name="product_areas", aggregation_source="groups", primary_keys=["id"]),
    # Event rows have no id of their own, so `id` is a hash of the bucket's grouping fields.
    "events": PendoEndpointConfig(
        name="events", event_source="events", primary_keys=["id"], incremental_fields=DAY_INCREMENTAL_FIELDS
    ),
    "page_events": PendoEndpointConfig(
        name="page_events", event_source="pageEvents", primary_keys=["id"], incremental_fields=DAY_INCREMENTAL_FIELDS
    ),
    "feature_events": PendoEndpointConfig(
        name="feature_events",
        event_source="featureEvents",
        primary_keys=["id"],
        incremental_fields=DAY_INCREMENTAL_FIELDS,
    ),
    "track_events": PendoEndpointConfig(
        name="track_events", event_source="trackEvents", primary_keys=["id"], incremental_fields=DAY_INCREMENTAL_FIELDS
    ),
    "survey_responses": PendoEndpointConfig(
        name="survey_responses",
        event_source="surveyResponses",
        primary_keys=["id"],
        incremental_fields=SURVEY_RESPONSE_INCREMENTAL_FIELDS,
        all_apps=False,
        grouped_events=False,
    ),
}

ENDPOINTS = tuple(PENDO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PENDO_ENDPOINTS.items()
}
