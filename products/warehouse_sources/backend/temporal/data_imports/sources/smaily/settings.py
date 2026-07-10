from dataclasses import dataclass, field

SEGMENT_SUBSCRIBERS = "segment_subscribers"
CAMPAIGN_STATISTICS = "campaign_statistics"


@dataclass
class SmailyEndpointConfig:
    name: str
    path: str
    # Smaily's page-index parameter is named `page` on some endpoints and `offset` on others
    # (both are page numbers, not row offsets). `None` means the endpoint is not paginated.
    page_param: str | None = None
    # Explicit per-request row limit. Some endpoints return ALL rows when `limit` is omitted or 0,
    # so we always pass the documented per-endpoint cap.
    page_size: int | None = None
    extra_params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Smaily list endpoints (https://smaily.com/help/api/). All are full refresh only: the API exposes
# no server-side `updated_after`-style filter on any list endpoint, so there is no reliable
# incremental cursor to advance (its Airbyte connector is likewise full-refresh only).
# Where the endpoint supports it we sort by `created_at` ascending so page boundaries stay stable
# while rows are inserted mid-sync.
SMAILY_ENDPOINTS: dict[str, SmailyEndpointConfig] = {
    "campaigns": SmailyEndpointConfig(
        name="campaigns",
        path="campaign.php",
        page_param="page",
        page_size=10000,
        extra_params={"sort_by": "created_at", "sort_order": "ASC"},
    ),
    CAMPAIGN_STATISTICS: SmailyEndpointConfig(
        # Fan-out: one request per campaign id (`campaign.php?id=...`), returning a single
        # statistics object per campaign.
        name=CAMPAIGN_STATISTICS,
        path="campaign.php",
    ),
    "segments": SmailyEndpointConfig(
        name="segments",
        path="list.php",
    ),
    SEGMENT_SUBSCRIBERS: SmailyEndpointConfig(
        # Fan-out: `contact.php` requires a `list` (segment id) param, so subscribers are synced
        # per segment. A subscriber can belong to several segments, hence the composite key —
        # `email` alone is only unique within one segment.
        name=SEGMENT_SUBSCRIBERS,
        path="contact.php",
        page_param="offset",
        page_size=25000,
        primary_keys=["segment_id", "email"],
    ),
    "templates": SmailyEndpointConfig(
        name="templates",
        path="templates.php",
        page_param="page",
        page_size=1000,
        extra_params={"sort_by": "created_at", "sort_order": "asc"},
    ),
    "automations": SmailyEndpointConfig(
        name="automations",
        path="autoresponder.php",
        page_param="page",
        page_size=10000,
        extra_params={"sort_by": "created_at", "sort_order": "ASC"},
    ),
    "ab_tests": SmailyEndpointConfig(
        name="ab_tests",
        path="split.php",
        page_param="offset",
        page_size=10000,
        extra_params={"sort_by": "created_at", "sort_order": "ASC"},
    ),
    "users": SmailyEndpointConfig(
        name="users",
        path="organizations/users.php",
        page_param="page",
        page_size=250,
    ),
}

ENDPOINTS = tuple(SMAILY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
