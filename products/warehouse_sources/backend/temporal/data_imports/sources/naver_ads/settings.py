from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

NAVER_ADS_BASE_URL = "https://api.searchad.naver.com"

# `recordSize` accepts up to 1,000 for ad groups and keywords.
PAGE_SIZE = 1000
STATS_IDS_PER_REQUEST = 100
# Naver can restate a day's metrics for up to 48 hours (invalid clicks, late partner data). Applied as the
# schemas' default incremental lookback, which users can change per table.
STATS_LOOKBACK_SECONDS = 2 * 24 * 60 * 60
# `/stats` serves the last two years at most.
MAX_HISTORY_DAYS = 730
STATS_TIMEZONE = "Asia/Seoul"

STAT_FIELDS: tuple[str, ...] = (
    "impCnt",
    "clkCnt",
    "salesAmt",
    "ctr",
    "cpc",
    "avgRnk",
    "ccnt",
    "crto",
    "convAmt",
    "ror",
    "cpConv",
    "viewCnt",
    "purchaseCcnt",
    "purchaseConvAmt",
    "purchaseRor",
)

EntityKind = Literal["campaign", "adgroup", "ad", "keyword"]


@frozen
class NaverAdsEntity:
    path: str
    id_field: str
    # The entity whose id filters this list. Naver lists ad groups per campaign and ads and keywords per ad group.
    parent: EntityKind | None = None
    parent_param: str | None = None
    # Whether the list takes `recordSize` and `baseSearchId`. The ads list returns everything in one response.
    keyset_paginated: bool = True


ENTITIES: dict[EntityKind, NaverAdsEntity] = {
    "campaign": NaverAdsEntity(path="/ncc/campaigns", id_field="nccCampaignId"),
    "adgroup": NaverAdsEntity(
        path="/ncc/adgroups", id_field="nccAdgroupId", parent="campaign", parent_param="nccCampaignId"
    ),
    "ad": NaverAdsEntity(
        path="/ncc/ads",
        id_field="nccAdId",
        parent="adgroup",
        parent_param="nccAdgroupId",
        keyset_paginated=False,
    ),
    "keyword": NaverAdsEntity(
        path="/ncc/keywords", id_field="nccKeywordId", parent="adgroup", parent_param="nccAdgroupId"
    ),
}


@frozen
class NaverAdsEndpoint:
    name: str
    entity: EntityKind
    primary_keys: tuple[str, ...]
    is_stats: bool = False
    # How far back a first sync of a stats table reads. Keyword stats cost one request per 100 keywords per day.
    history_days: int | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


def _stats_endpoint(name: str, entity: EntityKind, history_days: int) -> NaverAdsEndpoint:
    return NaverAdsEndpoint(
        name=name,
        entity=entity,
        primary_keys=("id", "date"),
        is_stats=True,
        history_days=history_days,
        incremental_fields=[incremental_field("date", IncrementalFieldType.Date)],
    )


ENDPOINTS: dict[str, NaverAdsEndpoint] = {
    "campaigns": NaverAdsEndpoint(name="campaigns", entity="campaign", primary_keys=("nccCampaignId",)),
    "adgroups": NaverAdsEndpoint(name="adgroups", entity="adgroup", primary_keys=("nccAdgroupId",)),
    "ads": NaverAdsEndpoint(name="ads", entity="ad", primary_keys=("nccAdId",)),
    "keywords": NaverAdsEndpoint(name="keywords", entity="keyword", primary_keys=("nccKeywordId",)),
    "campaign_stats": _stats_endpoint("campaign_stats", "campaign", history_days=365),
    "adgroup_stats": _stats_endpoint("adgroup_stats", "adgroup", history_days=365),
    "keyword_stats": _stats_endpoint("keyword_stats", "keyword", history_days=90),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()
}

STATS_ENDPOINTS: tuple[str, ...] = tuple(name for name, endpoint in ENDPOINTS.items() if endpoint.is_stats)
