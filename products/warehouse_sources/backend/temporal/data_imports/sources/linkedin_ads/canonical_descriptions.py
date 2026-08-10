"""Canonical, documentation-sourced descriptions for LinkedIn Ads endpoints and columns.

Sourced from the official LinkedIn Marketing API reference
(https://learn.microsoft.com/en-us/linkedin/marketing). Keyed by the `resource_name` values in
`schemas.py` `RESOURCE_SCHEMAS`, which match the `ExternalDataSchema.name` of a synced table. URN
reference fields are flattened into `*_id` virtual columns (e.g. `campaign_id`, `account_id`) and
analytics date ranges into `date_start` / `date_end` during sync. Columns absent here fall back to
LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Metrics shared by every analytics (stats) resource; merged into each stats entry.
_STATS_COLUMNS = {
    "date_start": "Start date of the reporting period for this row.",
    "date_end": "End date of the reporting period for this row.",
    "impressions": "Number of times an ad was shown.",
    "clicks": "Number of clicks on the ad.",
    "cost_in_usd": "Amount spent in USD over the reporting period.",
    "cost_in_local_currency": "Amount spent in the account's local currency over the reporting period.",
    "external_website_conversions": "Conversions tracked on an external website attributed to the ad.",
    "conversion_value_in_local_currency": "Total value of conversions in the account's local currency.",
    "landing_page_clicks": "Clicks that led to the ad's landing page.",
    "total_engagements": "Total engagements (clicks, reactions, comments, shares, follows) on the ad.",
    "video_views": "Number of video views.",
    "video_completions": "Number of times the video was watched to completion.",
    "one_click_leads": "Leads collected via one-click LinkedIn Lead Gen forms.",
    "follows": "Number of new followers attributed to the ad.",
}

# Professional demographic breakdowns carry the same metrics minus conversion value, which LinkedIn
# only reports for non-demographic pivots.
_DEMOGRAPHIC_STATS_COLUMNS = {
    key: value for key, value in _STATS_COLUMNS.items() if key != "conversion_value_in_local_currency"
}

_DEMOGRAPHIC_DOCS_URL = "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting"

_DEMOGRAPHIC_CAVEAT = (
    "LinkedIn approximates professional demographic metrics to protect member privacy: only the top "
    "100 values per creative per day are returned, values with fewer than 3 events are dropped, and "
    "the data is retained for two years."
)


CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "accounts": {
        "description": "A LinkedIn advertising account (ad account) used to run and bill campaigns.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-accounts",
        "columns": {
            "id": "Unique identifier for the ad account.",
            "name": "The ad account's name.",
            "status": "Status of the ad account (e.g. ACTIVE, CANCELED, DRAFT).",
            "type": "Type of the ad account (e.g. BUSINESS, ENTERPRISE).",
            "currency": "The account's billing currency.",
            "version": "Version metadata for optimistic concurrency.",
        },
    },
    "campaigns": {
        "description": "A LinkedIn ad campaign — a budget, schedule, and targeting wrapper around creatives.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaigns",
        "columns": {
            "id": "Unique identifier for the campaign.",
            "name": "The campaign's name.",
            "account_id": "ID of the ad account the campaign belongs to.",
            "campaign_group_id": "ID of the campaign group the campaign belongs to.",
            "status": "Status of the campaign (e.g. ACTIVE, PAUSED, DRAFT, COMPLETED, ARCHIVED).",
            "type": "The campaign's type (e.g. SPONSORED_UPDATES, TEXT_AD).",
            "cost_type": "How the campaign is charged (e.g. CPC, CPM, CPV).",
            "daily_budget": "The campaign's daily budget.",
            "unit_cost": "Bid amount per unit (click, impression, etc.).",
            "run_schedule": "Start and end schedule for the campaign.",
            "targeting_criteria": "The audience targeting criteria applied to the campaign.",
            "locale": "The campaign's locale.",
            "change_audit_stamps": "Created and last-modified audit timestamps.",
            "last_modified_time": "Time the campaign was last modified.",
            "created_time": "Time the campaign was created.",
            "version": "Version metadata for optimistic concurrency.",
        },
    },
    "campaign_groups": {
        "description": "A group of LinkedIn ad campaigns sharing a budget and schedule.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-campaign-groups",
        "columns": {
            "id": "Unique identifier for the campaign group.",
            "name": "The campaign group's name.",
            "account_id": "ID of the ad account the campaign group belongs to.",
            "status": "Status of the campaign group (e.g. ACTIVE, PAUSED, DRAFT, ARCHIVED).",
            "total_budget": "The campaign group's total budget.",
            "run_schedule": "Start and end schedule for the campaign group.",
            "change_audit_stamps": "Created and last-modified audit timestamps.",
            "created_time": "Time the campaign group was created.",
        },
    },
    "creatives": {
        "description": "A LinkedIn ad creative — the content shown to members within a campaign.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads/account-structure/create-and-manage-creatives",
        "columns": {
            "id": "Unique identifier for the creative.",
            "name": "The creative's name.",
            "account_id": "ID of the ad account the creative belongs to.",
            "campaign_id": "ID of the campaign the creative belongs to.",
            "intended_status": "The creative's intended status (e.g. ACTIVE, PAUSED, DRAFT).",
            "is_serving": "Whether the creative is currently being served.",
            "review": "The creative's ad review status.",
            "created_at": "Time the creative was created.",
            "last_modified_at": "Time the creative was last modified.",
            "created_time": "Time the creative was created.",
        },
    },
    "campaign_stats": {
        "description": "Daily performance analytics for LinkedIn ad campaigns, pivoted by campaign.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "campaign_id": "ID of the campaign these metrics are for.",
        },
    },
    "campaign_group_stats": {
        "description": "Daily performance analytics for LinkedIn ad campaign groups, pivoted by campaign group.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "campaign_group_id": "ID of the campaign group these metrics are for.",
        },
    },
    "creative_stats": {
        "description": "Daily performance analytics for LinkedIn ad creatives, pivoted by creative.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting",
        "columns": {
            **_STATS_COLUMNS,
            "creative_id": "ID of the creative these metrics are for.",
            "date_range": "The reporting date range these metrics cover.",
        },
    },
    "conversions": {
        "description": "A conversion rule defined on the ad account, describing an action on the advertiser's site that LinkedIn attributes back to ads.",
        "docs_url": "https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/conversion-tracking",
        "columns": {
            "id": "Unique identifier for the conversion rule.",
            "name": "Short name for the rule, shown in Campaign Manager and in reports.",
            "type": "What the member did (ADD_TO_CART, DOWNLOAD, INSTALL, KEY_PAGE_VIEW, LEAD, PURCHASE, SIGN_UP, OTHER).",
            "enabled": "Whether the rule is currently able to record conversion events.",
            "account_id": "ID of the ad account the conversion rule belongs to.",
            "campaigns": "Campaign URNs the conversion rule is associated with.",
            "attribution_type": "How conversions are counted: LAST_TOUCH_BY_CAMPAIGN (once per campaign) or LAST_TOUCH_BY_CONVERSION (once per conversion rule).",
            "conversion_method": "How the conversion is recorded, for example via the LinkedIn Insight Tag or the Conversions API.",
            "post_click_attribution_window_size": "Days after a click during which a conversion is still attributed, in days (1, 7 or 30).",
            "view_through_attribution_window_size": "Days after an impression during which a conversion is still attributed, in days (1, 7 or 30).",
            "value_amount": "Monetary value assigned to one conversion, as a decimal string.",
            "value_currency_code": "Currency of the conversion value, matching the ad account's currency.",
            "created_time": "Date the conversion rule was created.",
            "last_modified_time": "Date the conversion rule was last modified.",
        },
    },
    "member_company_stats": {
        "description": f"Daily ad analytics broken down by the company members work at. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "Organization URN of the member's company, for example urn:li:organization:1111. Results can include companies the campaign did not explicitly target.",
        },
    },
    "member_company_size_stats": {
        "description": f"Daily ad analytics broken down by the headcount band of the company members work at. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "The company size band the metrics belong to, as LinkedIn returns it.",
        },
    },
    "member_country_stats": {
        "description": f"Daily ad analytics broken down by the country members are in. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "Geo URN of the member's country, for example urn:li:geo:103644278. Resolve it with LinkedIn's Geo API.",
        },
    },
    "member_industry_stats": {
        "description": f"Daily ad analytics broken down by the industry members work in. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "Industry URN of the member's industry, for example urn:li:industry:96. Resolve it with LinkedIn's Industries API.",
        },
    },
    "member_job_title_stats": {
        "description": f"Daily ad analytics broken down by member job title. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "Title URN of the member's job title, for example urn:li:title:9. Resolve it with LinkedIn's Titles API.",
        },
    },
    "member_seniority_stats": {
        "description": f"Daily ad analytics broken down by member seniority. {_DEMOGRAPHIC_CAVEAT}",
        "docs_url": _DEMOGRAPHIC_DOCS_URL,
        "columns": {
            **_DEMOGRAPHIC_STATS_COLUMNS,
            "pivot_value": "Seniority URN of the member's seniority level, for example urn:li:seniority:6. Resolve it with LinkedIn's Seniorities API.",
        },
    },
}
