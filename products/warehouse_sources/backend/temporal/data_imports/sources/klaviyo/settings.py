from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class KlaviyoFanOutConfig:
    """Walk a parent collection and follow a per-parent child endpoint for each of its rows.

    The owning endpoint's `path` is a template formatted with `parent_id_column`, e.g.
    `/lists/{list_id}/profiles` with `parent_id_column="list_id"`.
    """

    parent_path: str  # collection whose ids the child path is fanned out over, e.g. "/lists"
    parent_page_size: int  # Klaviyo caps page[size] per endpoint; a larger value 400s the fan-out
    parent_id_column: str  # column written onto every child row identifying its parent
    # Emit flat {parent_id_column, profile_id, joined_group_at} membership rows instead of the
    # flattened resource. Group-membership endpoints return whole profiles; only the join matters.
    membership_rows: bool = False
    # Two-level fan-out: `parent_path` is itself a template formatted with this collection's ids,
    # and every child row also carries the grandparent's id column.
    grandparent: Optional["KlaviyoFanOutConfig"] = None


@dataclass
class KlaviyoValuesReportConfig:
    """A Klaviyo reporting query: POST a statistics request, get one row back per grouping.

    Reporting endpoints are aggregates over a rolling window rather than a resource collection, so
    they are always full refresh — there is no per-row cursor to advance.
    """

    report_type: str  # JSON:API resource type the request body declares
    statistics: list[str]  # statistics to request; rate statistics come back as fractions [0, 1]
    timeframe_key: str  # Klaviyo's predefined timeframe key, capped at one year by the API
    group_by: list[str]  # grouping attributes, which are also the row's primary key


@dataclass
class KlaviyoEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    default_incremental_field: str = "updated_at"
    partition_key: Optional[str] = (
        None  # Field to partition by (should be created_at style field for stable partitions)
    )
    base_filter: Optional[str] = None  # e.g., "equals(messages.channel,'email')"
    page_size: Optional[int] = None  # Override default page size (100)
    sort: Optional[str] = None  # Sort field for the endpoint
    default_lookback_days: Optional[int] = None  # Limit first sync to last N days instead of full history
    primary_keys: list[str] = field(default_factory=lambda: ["id"])  # Primary key columns for dedup
    should_sync_default: bool = True  # Whether the table is selected for sync by default in the UI
    # Extra query params merged into every request, e.g. a fields[...] sparse fieldset.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Safety overlap subtracted from the incremental watermark on every run, re-pulling a window of
    # rows that merge dedupes on the primary key. Composes additively with the per-schema
    # incremental_field_lookback_seconds the framework applies before the value reaches the source.
    incremental_lookback: Optional[timedelta] = None
    # Klaviyo's filter operator for the incremental cursor. Most collections accept `greater-than`;
    # a few (reviews) only document `greater-or-equal`, which re-pulls the boundary row that merge
    # then dedupes on the primary key.
    incremental_operator: str = "greater-than"
    # Set when the endpoint is a per-parent child collection rather than a top-level one.
    fan_out: Optional[KlaviyoFanOutConfig] = None
    # Set when the endpoint is a reporting query posted as a body rather than a paged collection.
    values_report: Optional[KlaviyoValuesReportConfig] = None
    # Shown next to the table in the schema picker.
    description: Optional[str] = None


# Every statistic Klaviyo's campaign and flow values reports accept. Both endpoints document the
# same set, so one list drives both tables.
VALUES_REPORT_STATISTICS = [
    "average_order_value",
    "bounce_rate",
    "bounced",
    "bounced_or_failed",
    "bounced_or_failed_rate",
    "click_rate",
    "click_to_open_rate",
    "clicks",
    "clicks_unique",
    "conversion_rate",
    "conversion_uniques",
    "conversion_value",
    "conversions",
    "delivered",
    "delivery_rate",
    "failed",
    "failed_rate",
    "message_segment_count_sum",
    "open_rate",
    "opens",
    "opens_unique",
    "recipients",
    "revenue_per_recipient",
    "spam_complaint_rate",
    "spam_complaints",
    "text_message_credit_usage_amount",
    "text_message_roi",
    "text_message_spend",
    "unsubscribe_rate",
    "unsubscribe_uniques",
    "unsubscribes",
]

# The widest window Klaviyo's reporting API allows is one year.
VALUES_REPORT_TIMEFRAME_KEY = "last_365_days"


KLAVIYO_ENDPOINTS: dict[str, KlaviyoEndpointConfig] = {
    "email_campaigns": KlaviyoEndpointConfig(
        name="email_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'email')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "sms_campaigns": KlaviyoEndpointConfig(
        name="sms_campaigns",
        path="/campaigns",
        base_filter="equals(messages.channel,'sms')",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "events": KlaviyoEndpointConfig(
        name="events",
        path="/events",
        default_incremental_field="datetime",
        partition_key="datetime",
        default_lookback_days=365,
        description="Only syncs the last 365 days on initial sync",
        incremental_fields=[
            {
                "label": "datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "flows": KlaviyoEndpointConfig(
        name="flows",
        path="/flows",
        default_incremental_field="updated",
        partition_key="created",
        page_size=50,  # Flows endpoint max is 50
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "lists": KlaviyoEndpointConfig(
        name="lists",
        path="/lists",
        default_incremental_field="updated",
        partition_key="created",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "metrics": KlaviyoEndpointConfig(
        name="metrics",
        path="/metrics",
        page_size=0,  # Metrics endpoint doesn't support pagination
        incremental_fields=[],
    ),
    "profiles": KlaviyoEndpointConfig(
        name="profiles",
        path="/profiles",
        default_incremental_field="updated",
        partition_key="created",
        # Klaviyo omits the subscriptions object (email/SMS/push consent detail) unless requested.
        # Carries no rate-limit penalty, unlike predictive_analytics (75/s -> 10/s), which stays
        # excluded. The list_profiles/segment_profiles fan-outs are unaffected: their own
        # extra_params restrict profile payloads to joined_group_at via a fields[profile] fieldset.
        extra_params={"additional-fields[profile]": "subscriptions"},
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description=(
            "Includes each profile's subscriptions object by default: consent status per channel "
            "(email, sms, push), global email suppressions in "
            "subscriptions.email.marketing.suppression, and per-list email suppressions in "
            "subscriptions.email.marketing.list_suppressions"
        ),
    ),
    # Klaviyo only exposes list membership through per-list endpoints (which can't be called from
    # HogQL), so the many-to-many can't be joined. This table fans out one paginated request per list
    # to produce a flat {list_id, profile_id, joined_group_at} join table; it's opt-in (off by
    # default) to avoid the extra API cost.
    #
    # Incremental sync filters on `joined_group_at` (updated on re-join, so re-joins are picked up),
    # but Klaviyo has no removal timestamp: profiles removed from a list only disappear on a full
    # refresh. The 24h lookback re-pulls joins that landed in already-fetched lists mid-run; merge
    # dedupes them on the primary key. No partition_key: the partitioned merge predicate includes
    # partition equality, and a re-join moves the row's joined_group_at to a new partition, which
    # would leave the old row behind as a duplicate.
    "list_profiles": KlaviyoEndpointConfig(
        name="list_profiles",
        path="/lists/{list_id}/profiles",
        default_incremental_field="joined_group_at",
        page_size=100,
        sort="-joined_group_at",
        extra_params={"fields[profile]": "joined_group_at"},
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "joined_group_at",
                "type": IncrementalFieldType.DateTime,
                "field": "joined_group_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["list_id", "profile_id"],
        should_sync_default=False,
        fan_out=KlaviyoFanOutConfig(
            # Klaviyo caps the /lists endpoint at a page size of 10 (larger values 400).
            parent_path="/lists",
            parent_page_size=10,
            parent_id_column="list_id",
            membership_rows=True,
        ),
        description=(
            "Maps which profiles belong to which list as {list_id, profile_id, joined_group_at} rows. "
            "Incremental syncs pick up new joins and re-joins; profiles removed from a list are only "
            "reflected on a full refresh. List membership is not the same as subscription: check the "
            "$consent array in the profiles table's properties column to see which channels (sms, "
            "email, push) a profile is currently subscribed to. Per-list email suppressions are in "
            "the profiles table's subscriptions column, under email.marketing.list_suppressions"
        ),
    ),
    # Segment membership has the same shape as list membership: Klaviyo only exposes it per segment,
    # so the many-to-many can't be joined from HogQL without materializing it. Opt-in because a fan
    # out costs one paginated request per segment.
    "segment_profiles": KlaviyoEndpointConfig(
        name="segment_profiles",
        path="/segments/{segment_id}/profiles",
        default_incremental_field="joined_group_at",
        page_size=100,
        sort="-joined_group_at",
        extra_params={"fields[profile]": "joined_group_at"},
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "joined_group_at",
                "type": IncrementalFieldType.DateTime,
                "field": "joined_group_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["segment_id", "profile_id"],
        should_sync_default=False,
        fan_out=KlaviyoFanOutConfig(
            # Klaviyo caps the /segments endpoint at a page size of 10.
            parent_path="/segments",
            parent_page_size=10,
            parent_id_column="segment_id",
            membership_rows=True,
        ),
        description=(
            "Maps which profiles belong to which segment as {segment_id, profile_id, joined_group_at} "
            "rows. Segments are recomputed by Klaviyo, so profiles that no longer match are only "
            "removed on a full refresh"
        ),
    ),
    "segments": KlaviyoEndpointConfig(
        name="segments",
        path="/segments",
        default_incremental_field="updated",
        partition_key="created",
        page_size=10,  # Segments endpoint max is 10
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Flows only expose their step structure per flow, and messages only per action, so the two
    # tables below are a one- and two-level fan out respectively.
    "flow_actions": KlaviyoEndpointConfig(
        name="flow_actions",
        path="/flows/{flow_id}/flow-actions",
        default_incremental_field="updated",
        partition_key="created",
        page_size=50,  # Flow actions endpoint max is 50
        sort="-updated",
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        fan_out=KlaviyoFanOutConfig(
            parent_path="/flows",
            parent_page_size=50,  # Flows endpoint max is 50
            parent_id_column="flow_id",
        ),
        description="One row per step in a flow, carrying the flow_id it belongs to",
    ),
    "flow_messages": KlaviyoEndpointConfig(
        name="flow_messages",
        path="/flow-actions/{flow_action_id}/flow-messages",
        default_incremental_field="updated",
        partition_key="created",
        page_size=50,  # Flow messages endpoint max is 50
        sort="-updated",
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        should_sync_default=False,
        fan_out=KlaviyoFanOutConfig(
            parent_path="/flows/{flow_id}/flow-actions",
            parent_page_size=50,
            parent_id_column="flow_action_id",
            grandparent=KlaviyoFanOutConfig(
                parent_path="/flows",
                parent_page_size=50,
                parent_id_column="flow_id",
            ),
        ),
        description=(
            "One row per message sent by a flow step, carrying the flow_action_id and flow_id it "
            "belongs to. Opt-in: it walks every action of every flow"
        ),
    ),
    "campaign_values_reports": KlaviyoEndpointConfig(
        name="campaign_values_reports",
        path="/campaign-values-reports",
        incremental_fields=[],
        primary_keys=["campaign_id", "campaign_message_id", "send_channel"],
        values_report=KlaviyoValuesReportConfig(
            report_type="campaign-values-report",
            statistics=VALUES_REPORT_STATISTICS,
            timeframe_key=VALUES_REPORT_TIMEFRAME_KEY,
            group_by=["campaign_id", "campaign_message_id", "send_channel"],
        ),
        description=(
            "Klaviyo's own computed performance statistics per campaign message over the last 365 "
            "days, replaced in full on every sync. Conversion statistics use the conversion metric "
            "recorded in the conversion_metric_id column"
        ),
    ),
    "flow_values_reports": KlaviyoEndpointConfig(
        name="flow_values_reports",
        path="/flow-values-reports",
        incremental_fields=[],
        primary_keys=["flow_id", "flow_message_id", "send_channel"],
        values_report=KlaviyoValuesReportConfig(
            report_type="flow-values-report",
            statistics=VALUES_REPORT_STATISTICS,
            timeframe_key=VALUES_REPORT_TIMEFRAME_KEY,
            group_by=["flow_id", "flow_message_id", "send_channel"],
        ),
        description=(
            "Klaviyo's own computed performance statistics per flow message over the last 365 days, "
            "replaced in full on every sync. Conversion statistics use the conversion metric recorded "
            "in the conversion_metric_id column"
        ),
    ),
    "templates": KlaviyoEndpointConfig(
        name="templates",
        path="/templates",
        default_incremental_field="updated",
        partition_key="created",
        page_size=10,  # Templates endpoint max is 10
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "forms": KlaviyoEndpointConfig(
        name="forms",
        path="/forms",
        default_incremental_field="updated_at",
        partition_key="created_at",
        page_size=100,
        sort="updated_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Klaviyo only documents greater-or-equal / less-or-equal on the review `created` filter, and
    # exposes no filter on `updated`, so `created` is the only usable cursor here.
    "reviews": KlaviyoEndpointConfig(
        name="reviews",
        path="/reviews",
        default_incremental_field="created",
        partition_key="created",
        page_size=100,
        sort="created",
        incremental_operator="greater-or-equal",
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "images": KlaviyoEndpointConfig(
        name="images",
        path="/images",
        default_incremental_field="updated_at",
        page_size=100,
        sort="updated_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "web_feeds": KlaviyoEndpointConfig(
        name="web_feeds",
        path="/web-feeds",
        default_incremental_field="updated",
        partition_key="created",
        page_size=20,  # Web feeds endpoint max is 20
        sort="updated",
        incremental_fields=[
            {
                "label": "updated",
                "type": IncrementalFieldType.DateTime,
                "field": "updated",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Klaviyo documents no timestamp filter on the collections below, so they are full refresh only.
    "catalog_items": KlaviyoEndpointConfig(
        name="catalog_items",
        path="/catalog-items",
        partition_key="created",
        page_size=100,
        sort="created",
        incremental_fields=[],
    ),
    "catalog_variants": KlaviyoEndpointConfig(
        name="catalog_variants",
        path="/catalog-variants",
        partition_key="created",
        page_size=100,
        sort="created",
        incremental_fields=[],
    ),
    "catalog_categories": KlaviyoEndpointConfig(
        name="catalog_categories",
        path="/catalog-categories",
        page_size=100,
        sort="created",
        incremental_fields=[],
    ),
    "coupons": KlaviyoEndpointConfig(
        name="coupons",
        path="/coupons",
        page_size=100,
        incremental_fields=[],
    ),
    # Klaviyo requires a filter on coupon.id or profile.id on the flat /coupon-codes collection, so
    # it can't be listed directly; fan out over /coupons and pull each coupon's codes instead.
    "coupon_codes": KlaviyoEndpointConfig(
        name="coupon_codes",
        path="/coupons/{coupon_id}/coupon-codes",
        page_size=100,
        incremental_fields=[],
        fan_out=KlaviyoFanOutConfig(
            parent_path="/coupons",
            parent_page_size=100,
            parent_id_column="coupon_id",
        ),
    ),
    "tags": KlaviyoEndpointConfig(
        name="tags",
        path="/tags",
        page_size=50,  # Tags endpoint max is 50
        sort="id",
        incremental_fields=[],
    ),
    "tag_groups": KlaviyoEndpointConfig(
        name="tag_groups",
        path="/tag-groups",
        page_size=25,  # Tag groups endpoint max is 25
        sort="id",
        incremental_fields=[],
    ),
    "push_tokens": KlaviyoEndpointConfig(
        name="push_tokens",
        path="/push-tokens",
        partition_key="created",
        page_size=100,
        incremental_fields=[],
    ),
    "data_sources": KlaviyoEndpointConfig(
        name="data_sources",
        path="/data-sources",
        page_size=100,
        incremental_fields=[],
    ),
    # The endpoints below expose no page[size] param, so they are requested unsized and paged only
    # through the cursor links Klaviyo returns.
    "custom_metrics": KlaviyoEndpointConfig(
        name="custom_metrics",
        path="/custom-metrics",
        page_size=0,
        incremental_fields=[],
    ),
    "object_types": KlaviyoEndpointConfig(
        name="object_types",
        path="/object-types",
        page_size=0,
        incremental_fields=[],
    ),
    "webhooks": KlaviyoEndpointConfig(
        name="webhooks",
        path="/webhooks",
        page_size=0,
        incremental_fields=[],
        # Klaviyo only offers the webhooks API to accounts with its paid Advanced KDP add-on and
        # 403s for everyone else even with the webhooks read scope granted, so a default-on table
        # would fail the first sync for most connections.
        should_sync_default=False,
        description="Requires Klaviyo's Advanced KDP add-on",
    ),
    "accounts": KlaviyoEndpointConfig(
        name="accounts",
        path="/accounts",
        page_size=0,
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(KLAVIYO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KLAVIYO_ENDPOINTS.items()
}
