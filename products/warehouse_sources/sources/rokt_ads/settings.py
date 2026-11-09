from typing import Literal, TypedDict

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.rokt.com"
TOKEN_URL = f"{BASE_URL}/auth/oauth2/token"

# The Query API groups rows by calendar day; `datetime` is only present in the response when
# `interval` is sent, so every report endpoint sends it.
REPORT_INTERVAL = "day"

# Rokt publishes no pagination for report queries, so each request covers a bounded window and the
# transport walks windows forward instead.
WINDOW_DAYS = 31

# First sync reaches this far back when the user has no incremental cursor yet.
INITIAL_BACKFILL_DAYS = 730

# Acquisitions and conversions are attributed by conversion time, so Rokt keeps restating recent
# days after they first land. Each incremental run re-reads this trailing window.
INCREMENTAL_LOOKBACK_SECONDS = 7 * 24 * 60 * 60

ReportKind = Literal["campaigns", "transactions"]

ACCOUNTS_ENDPOINT = "Accounts"


class MetadataEndpoint(TypedDict):
    # Query API dimensions whose distinct values are the path IDs of one metadata request.
    discovery_dimensions: list[str]
    # Path under BASE_URL, filled with the account ID and one discovered value per dimension.
    path: str
    # Response keys that hold the path IDs, in discovery_dimensions order.
    id_fields: list[str]
    primary_key: list[str]


class ReportEndpoint(TypedDict):
    kind: ReportKind
    dimensions: list[str]
    metrics: list[str]
    primary_key: list[str]


# Advertiser-side metrics. Every report on the `campaigns` resource asks for this set; the account's
# own `/campaigns/help` response narrows it at sync time, so an account that cannot serve a metric
# loses that column rather than failing the request.
CAMPAIGN_METRICS = [
    "impressions",
    "referrals",
    "referral_rate",
    "gross_cost",
    "net_cost",
    "cpr",
    "cpa",
    "click_thru_cpa",
    "view_thru_cpa",
    "acquisitions",
    "click_thru_acquisitions",
    "view_thru_acquisitions",
    "acquisitions_by_conversion_time",
    "conversions",
    "click_thru_conversions",
    "view_thru_conversions",
    "conversion_rate",
    "click_thru_conversion_rate",
    "view_thru_conversion_rate",
    "cost_per_impression",
    "copi",
    "acquisition_roas",
    "conversion_roas",
    "acquisitions_value",
    "acquisition_aov",
    "conversion_value",
    "conversion_aov",
]

# Partner-side (publisher) metrics, served by the `transactions` resource.
TRANSACTION_METRICS = [
    "transactions",
    "page_transactions",
    "rokt_transactions_per_transaction",
    "impressions",
    "layout_impressions",
    "referrals",
    "referral_rate",
]

ENDPOINTS: dict[str, ReportEndpoint] = {
    "CampaignPerformance": {
        "kind": "campaigns",
        "dimensions": ["campaign_id", "campaign_name", "campaign_objective", "campaign_country"],
        "metrics": CAMPAIGN_METRICS,
        "primary_key": ["datetime", "campaign_id", "campaign_country"],
    },
    "CreativePerformance": {
        "kind": "campaigns",
        "dimensions": ["campaign_id", "creative_id", "creative_name"],
        "metrics": CAMPAIGN_METRICS,
        "primary_key": ["datetime", "campaign_id", "creative_id"],
    },
    "AudiencePerformance": {
        "kind": "campaigns",
        "dimensions": ["campaign_id", "audience_name"],
        "metrics": CAMPAIGN_METRICS,
        "primary_key": ["datetime", "campaign_id", "audience_name"],
    },
    "CampaignDemographics": {
        "kind": "campaigns",
        "dimensions": ["campaign_id", "age_range", "gender", "device"],
        "metrics": CAMPAIGN_METRICS,
        "primary_key": ["datetime", "campaign_id", "age_range", "gender", "device"],
    },
    "TransactionPerformance": {
        "kind": "transactions",
        "dimensions": ["partner_vertical", "partner_sub_vertical", "page_type", "display_type"],
        "metrics": TRANSACTION_METRICS,
        "primary_key": ["datetime", "partner_vertical", "partner_sub_vertical", "page_type", "display_type"],
    },
}

# Rokt has no list endpoint for campaigns, creatives or audiences, so each metadata table discovers
# its IDs from the Query API, then reads the legacy metadata endpoint once per ID. Rokt keeps these
# endpoints because the Query API has no replacement for them.
METADATA_ENDPOINTS: dict[str, MetadataEndpoint] = {
    "CampaignMetadata": {
        "discovery_dimensions": ["campaign_id"],
        "path": "/metadata/accounts/{account_id}/campaigns/{0}",
        "id_fields": ["campaignId"],
        "primary_key": ["campaignId"],
    },
    "CreativeMetadata": {
        "discovery_dimensions": ["campaign_id", "creative_id"],
        "path": "/metadata/accounts/{account_id}/campaigns/{0}/creatives/{1}",
        "id_fields": ["campaignId", "creativeId"],
        "primary_key": ["campaignId", "creativeId"],
    },
    "AudienceMetadata": {
        "discovery_dimensions": ["campaign_id", "audience_id"],
        "path": "/metadata/accounts/{account_id}/campaigns/{0}/audiences/{1}",
        "id_fields": ["campaignId", "audienceId"],
        "primary_key": ["campaignId", "audienceId"],
    },
}

# Discovery only needs a row per ID, so it asks for the first of these metrics the account grants.
DISCOVERY_METRICS = ["impressions", "referrals", "gross_cost"]

SCHEMA_NAMES = [ACCOUNTS_ENDPOINT, *ENDPOINTS, *METADATA_ENDPOINTS]

PRIMARY_KEYS: dict[str, list[str]] = {
    ACCOUNTS_ENDPOINT: ["accountId"],
    **{name: endpoint["primary_key"] for name, endpoint in ENDPOINTS.items()},
    **{name: endpoint["primary_key"] for name, endpoint in METADATA_ENDPOINTS.items()},
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "datetime",
            "type": IncrementalFieldType.DateTime,
            "field": "datetime",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]
    for name in ENDPOINTS
}

DESCRIPTIONS = {
    ACCOUNTS_ENDPOINT: "Rokt accounts the connected credentials can read.",
    "CampaignPerformance": "Daily advertiser spend and outcome metrics per campaign.",
    "CreativePerformance": "Daily advertiser metrics per creative within a campaign.",
    "AudiencePerformance": "Daily advertiser metrics per targeted audience.",
    "CampaignDemographics": "Daily advertiser metrics split by age range, gender and device.",
    "TransactionPerformance": "Daily partner transaction and impression metrics.",
    "CampaignMetadata": "Type, objective, country and status of each campaign.",
    "CreativeMetadata": "Ad text, response options and status of each creative.",
    "AudienceMetadata": "Age range, gender and device targeting of each audience.",
}
