from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_DOCS = "https://advertising-api.newsbreak.com/hc/en-us/articles"
_REPORT_DOCS = f"{_DOCS}/37825594764941-Run-a-Synchronous-Report"

_REPORT_COLUMNS = {
    "date": "Day of the report row, in the report time zone.",
    "adAccountId": "Ad account ID.",
    "adAccount": "Ad account name.",
    "costDecimal": "Spend in cents.",
    "cost": "Spend in cents, as an integer.",
    "impression": "Number of impressions.",
    "click": "Number of clicks.",
    "conversion": "Number of conversions.",
    "conversionValueDecimal": "Total conversion value in cents.",
    "conversionValue": "Total conversion value in cents, as an integer.",
    "cpmDecimal": "Cost per thousand impressions in cents, -1.0 if not available.",
    "cpcDecimal": "Cost per click in cents, -1.0 if not available.",
    "cpaDecimal": "Cost per action in cents, -1.0 if not available.",
    "ctr": "Click-through rate times 10000 (basis points), -1 if not available.",
    "cvr": "Conversion rate times 10000 (basis points), -1 if not available.",
    "vpaDecimal": "Value per action in cents, -1.0 if not available.",
    "roas": "Return on ad spend, -1.0 if not available.",
    "completePaymentRoas": "Complete payment return on ad spend, -1.0 if not available.",
    "saleRoas": "Sale return on ad spend, -1.0 if not available.",
    "appPurchaseRoas": "App purchase return on ad spend, -1.0 if not available.",
    "appInAppAdImprRoas": "App in-app ad impression return on ad spend, -1.0 if not available.",
}
_CAMPAIGN_COLUMNS = {"campaignId": "Campaign ID.", "campaign": "Campaign name."}
_AD_SET_COLUMNS = {"adSetId": "Ad set ID.", "adSet": "Ad set name."}
_AD_COLUMNS = {"adId": "Ad ID.", "ad": "Ad name."}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "ad_accounts": {
        "description": "NewsBreak ad accounts in the connected organizations.",
        "docs_url": f"{_DOCS}/37869173867789-Get-Ad-Accounts",
        "columns": {
            "id": "Ad account ID.",
            "name": "Ad account name.",
            "createTime": "Creation time of the ad account, in Unix seconds.",
            "orgId": "ID of the organization that owns the ad account.",
            "orgName": "Name of the organization that owns the ad account.",
        },
    },
    "campaigns": {
        "description": "NewsBreak ad campaigns.",
        "docs_url": f"{_DOCS}/37869190998925-Get-Campaigns",
        "columns": {
            "id": "Campaign ID.",
            "name": "Campaign name.",
            "orgId": "Organization ID.",
            "adAccountId": "Ad account ID.",
            "objective": "Objective of the campaign.",
            "budget": "Campaign budget.",
            "onlineStatus": "Online status of the campaign.",
            "status": "Campaign status (ON or OFF).",
            "createTime": "Creation time of the campaign.",
            "updateTime": "Last update time of the campaign.",
        },
    },
    "ad_sets": {
        "description": "NewsBreak ad sets, with their budget, bidding, schedule and targeting.",
        "docs_url": f"{_DOCS}/37869226813965-Get-Ad-Sets",
        "columns": {
            "id": "Ad set ID.",
            "name": "Ad set name.",
            "orgId": "Organization ID.",
            "adAccountId": "Ad account ID.",
            "campaignId": "Campaign ID.",
            "trackingId": "Event tracking ID.",
            "budget": "Ad set budget in cents.",
            "budgetType": "Ad set budget type.",
            "status": "Ad set status.",
            "onlineStatus": "Online status of the ad set.",
            "startTime": "Start time of the ad set.",
            "endTime": "End time of the ad set.",
            "schedule": "Delivery schedule of the ad set.",
            "bidType": "Bid type of the ad set.",
            "bidRate": "Bid rate in cents.",
            "deliveryRate": "Delivery rate of the ad set.",
            "optimization": "Whether the creative is optimized.",
            "frequencyCaps": "Delivery frequency caps of the ad set.",
            "targeting": "Targeting of the ad set.",
            "createTime": "Creation time of the ad set.",
            "updateTime": "Last update time of the ad set.",
        },
    },
    "ads": {
        "description": "NewsBreak ads and their creatives.",
        "docs_url": f"{_DOCS}/37869300764813-Get-Ads",
        "columns": {
            "id": "Ad ID.",
            "name": "Ad name.",
            "adAccountId": "Ad account ID.",
            "campaignId": "Campaign ID.",
            "adSetId": "Ad set ID.",
            "clickTrackingUrl": "Click tracking URLs.",
            "impressionTrackingUrl": "Impression tracking URLs.",
            "status": "Status of the ad (ON or OFF).",
            "auditStatus": "Review status of the ad: PENDING, APPROVED or REJECTED.",
            "onlineStatus": "Online display status of the ad.",
            "statusTxt": "Explanation of the status of the ad.",
            "creative": "Creative of the ad: type, headline, asset, description, call to action and landing page.",
            "createTime": "Creation time of the ad.",
            "updateTime": "Last update time of the ad.",
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
