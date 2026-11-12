from dataclasses import field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

SEGMENT_SUBSCRIBERS = "segment_subscribers"
CAMPAIGN_STATISTICS = "campaign_statistics"
SEGMENT_RULES = "segment_rules"
AB_TEST_STATISTICS = "ab_test_statistics"
SUBSCRIBER_ACTIONS = "subscriber_actions"
MESSAGE_ACTIONS = "message_actions"
SEQ_ID_FIELD = "seq_id"


@frozen
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
    # Stable creation timestamp to partition by month. Set on the action logs, whose dense
    # integer `seq_id` keys would otherwise be bucketed one row per partition.
    partition_key: str | None = None


# Smaily list endpoints (https://smaily.com/help/api/). The list endpoints are full refresh only:
# the API exposes no server-side `updated_after`-style filter on them. The two action logs are the
# exception: they page by `since_seq_id`, which is also a server-side incremental cursor.
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
    SEGMENT_RULES: SmailyEndpointConfig(
        # Fan-out: one request per segment id (`list.php?id=...`), returning the segment with its
        # `filter_type` and `filter_data` rules.
        name=SEGMENT_RULES,
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
    AB_TEST_STATISTICS: SmailyEndpointConfig(
        # Fan-out: one request per A/B test id (`split.php?id=...`), returning one statistics
        # object per test section. The objects carry no id, so rows are keyed by their position.
        name=AB_TEST_STATISTICS,
        path="split.php",
        primary_keys=["ab_test_id", "section_index"],
    ),
    SUBSCRIBER_ACTIONS: SmailyEndpointConfig(
        name=SUBSCRIBER_ACTIONS,
        path="history.php",
        page_size=10000,
        primary_keys=[SEQ_ID_FIELD],
        partition_key="time",
    ),
    MESSAGE_ACTIONS: SmailyEndpointConfig(
        name=MESSAGE_ACTIONS,
        path="message/action/log.php",
        page_size=10000,
        primary_keys=[SEQ_ID_FIELD],
        partition_key="created_at",
    ),
    "users": SmailyEndpointConfig(
        name="users",
        path="organizations/users.php",
        page_param="page",
        page_size=250,
    ),
}

ENDPOINTS = tuple(SMAILY_ENDPOINTS.keys())

# Both action logs keep only the last 30 days, so an incremental sync is what keeps older actions
# in the warehouse.
ACTION_LOG_ENDPOINTS = (SUBSCRIBER_ACTIONS, MESSAGE_ACTIONS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    endpoint: [
        {
            "label": SEQ_ID_FIELD,
            "type": IncrementalFieldType.Integer,
            "field": SEQ_ID_FIELD,
            "field_type": IncrementalFieldType.Integer,
        }
    ]
    for endpoint in ACTION_LOG_ENDPOINTS
}
