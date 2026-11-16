"""Canonical, documentation-sourced descriptions for Singular tables and columns.

Sourced from the Singular Reporting API reference and the Metrics and Dimensions glossary
(https://support.singular.net/hc/en-us/articles/203389179). Keyed by the endpoint names in
`settings.py`. The `daily_report` columns depend on the dimensions and metrics a source is set up
with, so only the default ones are described here. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

REPORTING_API_URL = "https://support.singular.net/hc/en-us/articles/360045245692-Reporting-API-Reference"
SKADNETWORK_API_URL = "https://support.singular.net/hc/en-us/articles/360056377792"
AD_MONETIZATION_API_URL = "https://support.singular.net/hc/en-us/articles/360045674511"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_report": {
        "description": "Daily campaign statistics from the Singular Reporting API, one row per day and combination of the chosen dimensions.",
        "docs_url": "https://support.singular.net/hc/en-us/articles/203389179-Metrics-and-Dimensions",
        "columns": {
            "date": "The day the row's statistics cover.",
            "app": "The app name as configured in the Apps page.",
            "source": "The name of the data source (usually the ad network).",
            "os": "The operating system of the marketed product, such as iOS or Android.",
            "country_field": "The user's country, as reported by the network or derived from the network's targeting settings.",
            "adn_campaign_id": "The ID of the campaign, as pulled from the ad network.",
            "adn_campaign_name": "The name of the campaign, as pulled from the ad network.",
            "adn_cost": "Cost (ad spend) reported by the ad network, in the default currency configured in Singular.",
            "adn_impressions": "The number of ad views as reported by the ad network.",
            "adn_clicks": "The number of ad clicks as reported by the ad network.",
            "adn_installs": "The number of app installs or total conversions as reported by the ad network.",
        },
    },
    "skadnetwork_report": {
        "description": "Daily SKAdNetwork data combined with ad network cost and tracker data, by postback date.",
        "docs_url": SKADNETWORK_API_URL,
        "columns": {
            "date": "The SKAdNetwork postback date the row's statistics cover.",
            "app": "The app name.",
            "source": "The partner network.",
            "country_field": "The country, filled in from the network's campaign targeting when the campaign targets a single country.",
            "unified_campaign_id": "The campaign ID as used in regular Singular reports, not the campaign ID given by SKAdNetwork.",
            "unified_campaign_name": "The campaign name as used in regular Singular reports.",
            "adn_cost": "Cost as reported by the ad network.",
            "skan_report_network_impressions": "Ad impressions, as reported by the network.",
            "skan_report_network_clicks": "Ad clicks, as reported by the network.",
            "skan_installs": "Number of installs as reported by SKAdNetwork.",
            "tracker_installs": "Installs attributed by the tracker based on device matching, not on SKAdNetwork postbacks.",
            "skan_ecpi": "Effective cost per install: the total cost divided by the number of SKAdNetwork installs.",
            "skan_revenue": "Campaign revenue, regardless of the conversion model used.",
        },
    },
    "skadnetwork_raw_report": {
        "description": "Daily SKAdNetwork install counts from the raw postbacks, by postback date.",
        "docs_url": SKADNETWORK_API_URL,
        "columns": {
            "date": "The SKAdNetwork postback date the row's statistics cover.",
            "app": "The app name in Singular, derived from skan_app_id.",
            "source": "The ad network name as listed in Singular, derived from skan_network_id.",
            "skan_app_id": "The value of the 'app-id' parameter in Apple's SKAdNetwork postback.",
            "skan_network_id": "The value of the 'ad-network-id' parameter in Apple's SKAdNetwork postback.",
            "skan_campaign_id": "The campaign ID from the SKAdNetwork postback. In SKAN 4, the first two digits of the source ID.",
            "skan_publisher_id": "The value of the 'source-app-id' parameter in Apple's SKAdNetwork postback.",
            "skan_conversion_value": "The SKAdNetwork conversion value, a number between 0 and 63.",
            "skan_redownloads": "Whether Apple marked the install as a redownload by the same Apple ID.",
            "skan_validated": "Whether Singular confirmed with Apple that the postback represents an actual install.",
            "country_field": "The country, filled in from the network's campaign targeting when the campaign targets a single country.",
            "skan_installs": "The number of installs as reported by the SKAdNetwork framework.",
        },
    },
    "ad_monetization_report": {
        "description": "Daily ad monetization statistics that Singular pulls from your monetization networks.",
        "docs_url": AD_MONETIZATION_API_URL,
        "columns": {
            "date": "The day the row's statistics cover.",
            "app": "The application name.",
            "source": "The monetization network.",
            "os": "The user's device operating system, such as iOS or Android.",
            "ad_country": "The country in which the ad was served to the user.",
            "ad_type_name": "The name of the ad type (also known as ad format or ad unit), such as banner or rewarded video.",
            "ad_requests": "The number of ad requests reported by the network.",
            "filled_ad_requests": "The number of filled ad requests reported by the network. Equal to ad_impressions for networks that do not report it.",
            "ad_fill_rate": "The fill rate: filled ad requests divided by ad requests.",
            "ad_impressions": "Impressions reported by the ad network.",
            "ad_clicks": "Clicks reported by the ad network.",
            "ad_revenue": "Ad revenue reported by the ad network, converted to USD.",
            "ad_ecpm": "Effective cost per mille: total ad revenue divided by total impressions, times one thousand.",
        },
    },
    "filters": {
        "description": "One row per value a report dimension can be filtered by, such as each OS code or source, with its display name.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "dimension": "The dimension name used in report queries, such as os or source.",
            "dimension_display_name": "The name of the dimension as it appears in the Singular platform.",
            "name": "The value as used in report filters, such as an OS code.",
            "display_name": "The name of the value as it appears in the Singular platform.",
        },
    },
    "custom_dimensions": {
        "description": "A custom dimension defined in the Singular account. Use its ID as a dimension in a report.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "id": "Identifier of the custom dimension, used in report queries.",
            "display_name": "The name of the custom dimension as it appears in the Singular platform.",
        },
    },
    "cohort_metrics": {
        "description": "A cohort metric or in-app event available to the Singular account for report queries.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "name": "The identifier of the metric for use in API queries.",
            "display_name": "The name of the metric as it appears in the Singular platform.",
        },
    },
    "conversion_metrics": {
        "description": "A conversion event available to the Singular account, usable as a metric in report queries.",
        "docs_url": REPORTING_API_URL,
        "columns": {
            "name": "The auto-generated identifier of the event, used in report queries.",
            "display_name": "The name of the conversion event as configured in the Events page.",
        },
    },
}
