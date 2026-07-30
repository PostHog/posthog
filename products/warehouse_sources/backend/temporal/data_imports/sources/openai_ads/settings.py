from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

OPENAI_ADS_BASE_URL = "https://api.ads.openai.com"

# Entity list endpoints (campaigns, ad groups, ads) allow up to 500 per page.
LIST_PAGE_SIZE = 500
# Insights allow up to 2000 per page; 500 keeps individual pages modest.
INSIGHTS_PAGE_SIZE = 500

# Insights buckets for recent days get restated as reporting catches up (delivery is real-time,
# reporting is not), so each incremental run re-reads a trailing window and merge dedupes on the
# bucket row id.
INSIGHTS_LOOKBACK_SECONDS = 60 * 60 * 24 * 3

# Delivery metrics exposed by every insights aggregation level, requested as
# `{aggregation_level}.{metric}` and returned as bare wire keys (impressions, clicks, ...).
_INSIGHTS_METRICS = ("impressions", "clicks", "spend", "ctr", "cpc", "cpm")


def _insights_fields(level: str, metadata: tuple[str, ...]) -> list[str]:
    return [
        "metadata.readable_time",
        *(f"{level}.{name}" for name in metadata),
        *(f"{level}.{metric}" for metric in _INSIGHTS_METRICS),
    ]


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class OpenAIAdsEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Stable creation-style timestamp used for datetime partitioning — never an
    # `updated_at`-style field.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where the API has a genuine server-side time filter: the insights endpoints'
    # `time_ranges[]`. Entity lists expose created_at/updated_at on rows but no date filter
    # param, so they are full-refresh only.
    supports_incremental: bool = False
    sort_mode: SortMode = "asc"
    # Insights-only: the `aggregation_level` picking the row entity, and the `fields[]`
    # projection requested for that level.
    aggregation_level: Optional[str] = None
    insights_fields: list[str] = field(default_factory=list)
    default_incremental_lookback_seconds: Optional[int] = None


def _insights_endpoint(name: str, level: str, metadata: tuple[str, ...]) -> OpenAIAdsEndpointConfig:
    return OpenAIAdsEndpointConfig(
        name=name,
        # Account-scoped insights cover every entity of the account; `aggregation_level`
        # picks the row entity, so no per-entity fan-out is needed.
        path="/v1/ad_account/insights",
        # The API's composite bucket id ("start=<unix>:end=<unix>:entity_id=<id>") is unique and
        # stable per (bucket, entity) as long as no sort[]/segments[] params are sent (those
        # append suffixes to the id).
        primary_keys=["id"],
        partition_key="start_time",
        incremental_fields=[_datetime_incremental_field("start_time")],
        supports_incremental=True,
        # Row ordering within a multi-day window is undocumented and unverified, so "desc" makes
        # the pipeline commit the incremental watermark only at sync completion — correct
        # regardless of arrival order.
        sort_mode="desc",
        aggregation_level=level,
        insights_fields=_insights_fields(level, metadata),
        default_incremental_lookback_seconds=INSIGHTS_LOOKBACK_SECONDS,
    )


OPENAI_ADS_ENDPOINTS: dict[str, OpenAIAdsEndpointConfig] = {
    "campaigns": OpenAIAdsEndpointConfig(
        name="campaigns",
        path="/v1/campaigns",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # `GET /v1/ad_groups` requires a `campaign_id` query param, so ad groups fan out one
    # listing per campaign. The response objects don't carry their parent id — the transport
    # stamps `campaign_id` onto every row, and the key is composite because ad group id
    # uniqueness across campaigns isn't documented.
    "ad_groups": OpenAIAdsEndpointConfig(
        name="ad_groups",
        path="/v1/ad_groups",
        primary_keys=["campaign_id", "id"],
        partition_key="created_at",
    ),
    # `GET /v1/ads` requires an `ad_group_id` query param — a two-level fan-out
    # (campaigns -> ad groups -> ads). Rows are stamped with both parent ids.
    "ads": OpenAIAdsEndpointConfig(
        name="ads",
        path="/v1/ads",
        primary_keys=["ad_group_id", "id"],
        partition_key="created_at",
    ),
    "campaign_insights": _insights_endpoint("campaign_insights", "campaign", ("id", "name", "status")),
    "ad_group_insights": _insights_endpoint("ad_group_insights", "ad_group", ("id", "name", "status")),
    "ad_insights": _insights_endpoint("ad_insights", "ad", ("id", "name", "title", "status", "review_status")),
    "ad_account_insights": _insights_endpoint("ad_account_insights", "ad_account", ("name",)),
}

ENDPOINTS = tuple(OPENAI_ADS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in OPENAI_ADS_ENDPOINTS.items()
}
