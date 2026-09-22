from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

QUERY_API_DOCS = "https://docs.rokt.com/developers/api-reference/reporting/query-api/"

# Shared advertiser metric columns. Every campaigns-resource table reports the same metric set, so
# the descriptions are written once and spread into each table below.
_CAMPAIGN_METRIC_COLUMNS = {
    "datetime": "Start of the calendar day the metrics cover, in the report time zone.",
    "impressions": "Total advertisement impressions.",
    "referrals": "Total positive engagements on ads.",
    "referral_rate": "Referrals per impression.",
    "gross_cost": "Total ad spend on the Rokt platform.",
    "net_cost": "Total ad spend minus the scrub rate.",
    "cpr": "Average cost per referral.",
    "cpa": "Average cost per acquisition across click-thru and view-thru.",
    "click_thru_cpa": "Average cost per click-thru acquisition.",
    "view_thru_cpa": "Average cost per view-thru acquisition.",
    "acquisitions": "Total acquisitions.",
    "click_thru_acquisitions": "Click-thru acquisitions attributed to the campaign period.",
    "view_thru_acquisitions": "Total view-thru acquisitions.",
    "acquisitions_by_conversion_time": "All acquisitions attributed to the time the conversion happened.",
    "conversions": "Total conversions.",
    "click_thru_conversions": "Total click-thru conversions.",
    "view_thru_conversions": "Total view-thru conversions.",
    "conversion_rate": "Average conversion rate across click-thru and view-thru.",
    "click_thru_conversion_rate": "Average click-thru conversion rate.",
    "view_thru_conversion_rate": "Average view-thru conversion rate.",
    "cost_per_impression": "Average cost per impression.",
    "copi": "Average conversions per impression, counting acquisitions.",
    "acquisition_roas": "Return on ad spend for all acquisitions.",
    "conversion_roas": "Return on ad spend for all conversions.",
    "acquisitions_value": "Total value of acquisitions, in USD.",
    "acquisition_aov": "Average order value of acquisitions, in USD.",
    "conversion_value": "Total value of all conversions, in USD.",
    "conversion_aov": "Average order value of conversions, in USD.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "Accounts": {
        "description": "Rokt accounts the connected app credentials can read.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            "accountId": "Unique identifier for the Rokt account.",
            "accountName": "Display name of the account.",
            "countryCode": "Country the account is registered in.",
            "accountOwner": "Email address of the account owner.",
            "accountCurrencyCode": "Currency the account reports in.",
            "accountTimezone": "Olson time zone name the account reports in.",
            "accountTimezoneOffset": "Offset of the account time zone from UTC, in minutes.",
        },
    },
    "CampaignPerformance": {
        "description": "Daily advertiser spend and outcome metrics, one row per campaign, campaign country and day.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            **_CAMPAIGN_METRIC_COLUMNS,
            "campaign_id": "Identifier of the campaign.",
            "campaign_name": "Name of the campaign.",
            "campaign_objective": "Objective the campaign optimizes for.",
            "campaign_country": "Country the campaign runs in.",
        },
    },
    "CreativePerformance": {
        "description": "Daily advertiser metrics, one row per creative, campaign and day.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            **_CAMPAIGN_METRIC_COLUMNS,
            "campaign_id": "Identifier of the campaign the creative belongs to.",
            "creative_id": "Identifier of the creative.",
            "creative_name": "Name of the creative.",
        },
    },
    "AudiencePerformance": {
        "description": "Daily advertiser metrics, one row per targeted audience, campaign and day.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            **_CAMPAIGN_METRIC_COLUMNS,
            "campaign_id": "Identifier of the campaign the audience belongs to.",
            "audience_name": "Name of the targeted audience.",
        },
    },
    "CampaignDemographics": {
        "description": "Daily advertiser metrics split by the age range, gender and device of the user.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            **_CAMPAIGN_METRIC_COLUMNS,
            "campaign_id": "Identifier of the campaign.",
            "age_range": "Age range of the user.",
            "gender": "Gender of the user.",
            "device": "Device the user was on.",
        },
    },
    "TransactionPerformance": {
        "description": "Daily partner transaction and impression metrics, split by vertical, page type and display type.",
        "docs_url": QUERY_API_DOCS,
        "columns": {
            "datetime": "Start of the calendar day the metrics cover, in the report time zone.",
            "partner_vertical": "Vertical of the partner.",
            "partner_sub_vertical": "Sub-vertical of the partner.",
            "page_type": "Type of page the user was on.",
            "display_type": "Type of display the ad was shown on.",
            "transactions": "Total number of transactions.",
            "page_transactions": "Total transactions processed by the page.",
            "rokt_transactions_per_transaction": "Rokt transactions per transaction.",
            "impressions": "Total advertisement impressions.",
            "layout_impressions": "Advertisement impressions counted by layout.",
            "referrals": "Total positive engagements on ads.",
            "referral_rate": "Referrals per impression.",
        },
    },
}
