from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://advertising-api.newsbreak.com/hc/en-us/articles"
_REPORT_DOCS = f"{_DOCS}/37825594764941-Run-a-Synchronous-Report"

# Column keys are the snake_case names the pipeline gives the API fields (`costDecimal` -> `cost_decimal`).
_REPORT_COLUMNS = {
    "date": "Day of the report row, in the report time zone.",
    "ad_account_id": "Ad account ID.",
    "ad_account": "Ad account name.",
    "cost_decimal": "Spend in cents.",
    "cost": "Spend in cents, as an integer.",
    "impression": "Number of impressions.",
    "click": "Number of clicks.",
    "conversion": "Number of conversions.",
    "conversion_value_decimal": "Total conversion value in cents.",
    "conversion_value": "Total conversion value in cents, as an integer.",
    "cpm_decimal": "Cost per thousand impressions in cents, -1.0 if not available.",
    "cpc_decimal": "Cost per click in cents, -1.0 if not available.",
    "cpa_decimal": "Cost per action in cents, -1.0 if not available.",
    "ctr": "Click-through rate times 10000 (basis points), -1 if not available.",
    "cvr": "Conversion rate times 10000 (basis points), -1 if not available.",
    "vpa_decimal": "Value per action in cents, -1.0 if not available.",
    "roas": "Return on ad spend, -1.0 if not available.",
    "complete_payment_roas": "Complete payment return on ad spend, -1.0 if not available.",
    "sale_roas": "Sale return on ad spend, -1.0 if not available.",
    "app_purchase_roas": "App purchase return on ad spend, -1.0 if not available.",
    "app_in_app_ad_impr_roas": "App in-app ad impression return on ad spend, -1.0 if not available.",
}
_CAMPAIGN_COLUMNS = {"campaign_id": "Campaign ID.", "campaign": "Campaign name."}
_AD_SET_COLUMNS = {"ad_set_id": "Ad set ID.", "ad_set": "Ad set name."}
_AD_COLUMNS = {"ad_id": "Ad ID.", "ad": "Ad name."}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ad_accounts": {
        "description": "NewsBreak ad accounts in the connected organizations.",
        "docs_url": f"{_DOCS}/37869173867789-Get-Ad-Accounts",
        "columns": {
            "id": "Ad account ID.",
            "name": "Ad account name.",
            "create_time": "Creation time of the ad account, in Unix seconds.",
            "org_id": "ID of the organization that owns the ad account.",
            "org_name": "Name of the organization that owns the ad account.",
        },
    },
    "campaigns": {
        "description": "NewsBreak ad campaigns.",
        "docs_url": f"{_DOCS}/37869190998925-Get-Campaigns",
        "columns": {
            "id": "Campaign ID.",
            "name": "Campaign name.",
            "org_id": "Organization ID.",
            "ad_account_id": "Ad account ID.",
            "objective": "Objective of the campaign.",
            "budget": "Campaign budget.",
            "online_status": "Online status of the campaign.",
            "status": "Campaign status (ON or OFF).",
            "create_time": "Creation time of the campaign.",
            "update_time": "Last update time of the campaign.",
        },
    },
    "ad_sets": {
        "description": "NewsBreak ad sets, with their budget, bidding, schedule and targeting.",
        "docs_url": f"{_DOCS}/37869226813965-Get-Ad-Sets",
        "columns": {
            "id": "Ad set ID.",
            "name": "Ad set name.",
            "org_id": "Organization ID.",
            "ad_account_id": "Ad account ID.",
            "campaign_id": "Campaign ID.",
            "tracking_id": "Event tracking ID.",
            "budget": "Ad set budget in cents.",
            "budget_type": "Ad set budget type.",
            "status": "Ad set status.",
            "online_status": "Online status of the ad set.",
            "start_time": "Start time of the ad set.",
            "end_time": "End time of the ad set.",
            "schedule": "Delivery schedule of the ad set.",
            "bid_type": "Bid type of the ad set.",
            "bid_rate": "Bid rate in cents.",
            "delivery_rate": "Delivery rate of the ad set.",
            "optimization": "Whether the creative is optimized.",
            "frequency_caps": "Delivery frequency caps of the ad set.",
            "targeting": "Targeting of the ad set.",
            "create_time": "Creation time of the ad set.",
            "update_time": "Last update time of the ad set.",
        },
    },
    "ads": {
        "description": "NewsBreak ads and their creatives.",
        "docs_url": f"{_DOCS}/37869300764813-Get-Ads",
        "columns": {
            "id": "Ad ID.",
            "name": "Ad name.",
            "ad_account_id": "Ad account ID.",
            "campaign_id": "Campaign ID.",
            "ad_set_id": "Ad set ID.",
            "click_tracking_url": "Click tracking URLs.",
            "impression_tracking_url": "Impression tracking URLs.",
            "status": "Status of the ad (ON or OFF).",
            "audit_status": "Review status of the ad: PENDING, APPROVED or REJECTED.",
            "online_status": "Online display status of the ad.",
            "status_txt": "Explanation of the status of the ad.",
            "creative": "Creative of the ad: type, headline, asset, description, call to action and landing page.",
            "create_time": "Creation time of the ad.",
            "update_time": "Last update time of the ad.",
        },
    },
    "ad_account_daily_report": {
        "description": "Daily NewsBreak ad performance for each ad account.",
        "docs_url": _REPORT_DOCS,
        "columns": _REPORT_COLUMNS,
    },
    "campaign_daily_report": {
        "description": "Daily NewsBreak ad performance for each campaign.",
        "docs_url": _REPORT_DOCS,
        "columns": {**_REPORT_COLUMNS, **_CAMPAIGN_COLUMNS},
    },
    "ad_set_daily_report": {
        "description": "Daily NewsBreak ad performance for each ad set.",
        "docs_url": _REPORT_DOCS,
        "columns": {**_REPORT_COLUMNS, **_CAMPAIGN_COLUMNS, **_AD_SET_COLUMNS},
    },
    "ad_daily_report": {
        "description": "Daily NewsBreak ad performance for each ad.",
        "docs_url": _REPORT_DOCS,
        "columns": {**_REPORT_COLUMNS, **_CAMPAIGN_COLUMNS, **_AD_SET_COLUMNS, **_AD_COLUMNS},
    },
}
