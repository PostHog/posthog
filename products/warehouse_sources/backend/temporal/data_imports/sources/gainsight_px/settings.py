from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Gainsight PX runs regional deployments. An API key belongs to a single subscription that lives in
# one region, so the host is picked by the `region` form field rather than a user-supplied URL — the
# set is fixed, so there is no SSRF surface.
GAINSIGHT_PX_HOSTS: dict[str, str] = {
    "us": "https://api.aptrinsic.com/v1",
    "eu": "https://api-eu.aptrinsic.com/v1",
    "us2": "https://api-us2.aptrinsic.com/v1",
}

# The `pageSize` cap differs per endpoint and a request above an endpoint's cap is rejected with a
# 400, so every endpoint carries its own size. Scroll endpoints (users/accounts) allow up to 1000,
# engagement/articles/kcbot allow up to 500, and feature/segment allow only 200. The `/events/*`
# streams are scroll-paginated and share the 1000 cap.
SCROLL_PAGE_SIZE = 1000
PAGE_NUMBER_PAGE_SIZE = 500
FEATURE_SEGMENT_PAGE_SIZE = 200

PaginationMode = Literal["scroll", "page"]

# Date fields come back as epoch-millisecond integers. We convert them to real datetimes before
# yielding so partition columns type as timestamps in the warehouse — the partitioner's integer
# branch assumes epoch *seconds*, so raw millis would produce nonsense partitions. `releaseDate`
# on articles is an ISO string, so it is deliberately excluded.
EPOCH_MILLIS_FIELDS: frozenset[str] = frozenset(
    {
        "createDate",
        "lastModifiedDate",
        "lastSeenDate",
        "signUpDate",
        "firstVisitDate",
        "renewalDate",
        "createdDate",
        "modifiedDate",
        "date",
        "executionDate",
    }
)

# The `/events/*` streams accept `filter=date>=<epoch millis>` and `sort=date`, which is what makes
# them incremental. Events are immutable, so `date` never changes after capture.
EVENT_DATE_FIELD = "date"
# An events request without a date range returns only the last day, and a range above 190 days is a
# 400, so event syncs walk explicit windows. 180 days leaves headroom under the cap.
EVENT_WINDOW_DAYS = 180
# How far back the first sync (and every full refresh) of an event table reaches. The API documents
# no retention limit, so this bounds the backfill.
EVENT_BACKFILL_DAYS = 730
EVENT_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": EVENT_DATE_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": EVENT_DATE_FIELD,
        "field_type": IncrementalFieldType.DateTime,
    }
]


@dataclass(frozen=False)
class GainsightPxEndpointConfig:
    name: str
    path: str
    # The list of records is wrapped under a named key that varies per endpoint (e.g. `users`,
    # `articleExternalViewList`); this is that key.
    data_key: str
    pagination: PaginationMode
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Must be a STABLE creation datetime (never `lastModifiedDate`/`lastSeenDate`) so partitions
    # don't rewrite every sync. `None` for resources the API returns without a creation timestamp.
    partition_key: str | None = None
    page_size: int = SCROLL_PAGE_SIZE
    # Only the `/events/*` streams and survey responses expose a server-side date filter; the entity
    # endpoints have no "updated since" filter and stay full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# The entity endpoints are full refresh: the scroll endpoints
# (users/accounts) accept only `filter`/`sort`/`scrollId`, and the page-number endpoints accept only
# `pageNumber`/`pageSize` — none document an "updated since" server-side filter.
GAINSIGHT_PX_ENDPOINTS: dict[str, GainsightPxEndpointConfig] = {
    "accounts": GainsightPxEndpointConfig(
        name="accounts",
        path="/accounts",
        data_key="accounts",
        pagination="scroll",
        partition_key="createDate",
    ),
    "users": GainsightPxEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        pagination="scroll",
        partition_key="createDate",
    ),
    "features": GainsightPxEndpointConfig(
        name="features",
        path="/feature",
        data_key="features",
        pagination="page",
        page_size=FEATURE_SEGMENT_PAGE_SIZE,
    ),
    "segments": GainsightPxEndpointConfig(
        name="segments",
        path="/segment",
        data_key="segments",
        pagination="page",
        page_size=FEATURE_SEGMENT_PAGE_SIZE,
    ),
    "engagements": GainsightPxEndpointConfig(
        name="engagements",
        path="/engagement",
        data_key="engagements",
        pagination="page",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "articles": GainsightPxEndpointConfig(
        name="articles",
        path="/articles",
        data_key="articleExternalViewList",
        pagination="page",
        partition_key="createdDate",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "kc_bots": GainsightPxEndpointConfig(
        name="kc_bots",
        path="/kcbot",
        data_key="kcList",
        pagination="page",
        partition_key="createdDate",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "page_view_events": GainsightPxEndpointConfig(
        name="page_view_events",
        path="/events/pageView",
        data_key="results",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "session_events": GainsightPxEndpointConfig(
        name="session_events",
        path="/events/session",
        data_key="sessionInitializedEvents",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "engagement_view_events": GainsightPxEndpointConfig(
        name="engagement_view_events",
        path="/events/engagementView",
        data_key="results",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "feature_match_events": GainsightPxEndpointConfig(
        name="feature_match_events",
        path="/events/feature_match",
        data_key="featureMatchEvents",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "segment_match_events": GainsightPxEndpointConfig(
        name="segment_match_events",
        path="/events/segment_match",
        # The vendor spec wraps segment matches under the same key as feature matches.
        data_key="featureMatchEvents",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "custom_events": GainsightPxEndpointConfig(
        name="custom_events",
        path="/events/custom",
        data_key="customEvents",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    "identify_events": GainsightPxEndpointConfig(
        name="identify_events",
        path="/events/identify",
        data_key="identifyEvents",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
    # Survey responses are engagement view events filtered to survey content, so they take the same
    # date window filter and scroll pagination as the `/events/*` streams.
    "survey_responses": GainsightPxEndpointConfig(
        name="survey_responses",
        path="/survey/responses",
        data_key="results",
        pagination="scroll",
        primary_keys=["eventId"],
        partition_key=EVENT_DATE_FIELD,
        incremental_fields=EVENT_INCREMENTAL_FIELDS,
    ),
}

ENDPOINTS = tuple(GAINSIGHT_PX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GAINSIGHT_PX_ENDPOINTS.items()
}
