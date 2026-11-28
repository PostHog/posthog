from products.warehouse_sources.sources.sdk import CanonicalDescriptions

_REPORT_DIMENSION_COLUMNS = {
    "date": "The day the row describes, in the account's reporting time zone.",
    "app": "The unique ID of the mobile app, for example ca-app-pub-1234~1234.",
    "app_name": "The display name of the app.",
    "ad_unit": "The unique ID of the ad unit, for example ca-app-pub-1234/1234.",
    "ad_unit_name": "The display name of the ad unit.",
    "country": "CLDR country code of the place where the ad views or clicks occurred, for example US or FR.",
    "format": "Format of the ad unit, for example banner or native.",
    "platform": "Mobile OS platform of the app, for example Android or iOS.",
    "currency_code": "ISO 4217 currency code of the earnings columns, which is the account's currency.",
}

_COMMON_METRIC_COLUMNS = {
    "ad_requests": "The number of ad requests.",
    "clicks": "The number of times a user clicked an ad.",
    "estimated_earnings": "The estimated earnings of the AdMob publisher, in the account's currency.",
    "estimated_earnings_micros": "The estimated earnings in micros: one million micros is one unit of the currency.",
    "impressions": "The total number of ads shown to users.",
    "impression_ctr": "The ratio of clicks over impressions.",
    "matched_requests": "The number of times ads were returned in response to a request.",
    "match_rate": "The ratio of matched ad requests over the total ad requests.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "network_report": {
        "description": (
            "Daily AdMob Network report: earnings and delivery metrics for ads served by the AdMob Network, "
            "by app, ad unit, country, format and platform."
        ),
        "docs_url": "https://developers.google.com/admob/api/v1/reference/rest/v1/accounts.networkReport/generate",
        "columns": {
            **_REPORT_DIMENSION_COLUMNS,
            **_COMMON_METRIC_COLUMNS,
            "impression_rpm": "The estimated earnings per thousand ad impressions (eCPM), in the account's currency.",
            "impression_rpm_micros": "The estimated earnings per thousand ad impressions, in micros.",
            "show_rate": "The ratio of ads that were displayed over ads that were returned.",
        },
    },
    "mediation_report": {
        "description": (
            "Daily AdMob Mediation report: earnings and delivery metrics for every ad source in your mediation "
            "groups, by app, ad unit, ad source, mediation group, country, format and platform."
        ),
        "docs_url": "https://developers.google.com/admob/api/v1/reference/rest/v1/accounts.mediationReport/generate",
        "columns": {
            **_REPORT_DIMENSION_COLUMNS,
            **_COMMON_METRIC_COLUMNS,
            "ad_source": "The unique ID of the ad source, for example 5450213213286189855.",
            "ad_source_name": "The name of the ad source, for example AdMob Network.",
            "mediation_group": "The unique ID of the mediation group, for example ca-app-pub-1234:mg:1234.",
            "mediation_group_name": "The name of the mediation group.",
            "observed_ecpm": "The third-party ad network's estimated average eCPM, in the account's currency.",
            "observed_ecpm_micros": "The third-party ad network's estimated average eCPM, in micros.",
        },
    },
    "apps": {
        "description": "The apps of the AdMob account, one row per app and platform.",
        "docs_url": "https://developers.google.com/admob/api/v1/reference/rest/v1/accounts.apps/list",
        "columns": {
            "name": "Resource name of the app, in the format accounts/{publisher_id}/apps/{app_id_fragment}.",
            "app_id": "The externally visible ID of the app, for example ca-app-pub-9876543210987654~0123456789.",
            "platform": "The platform of the app: IOS or ANDROID.",
            "app_approval_state": "The approval state of the app.",
            "manual_app_info_display_name": "The display name of the app as shown in the AdMob UI.",
            "linked_app_info_app_store_id": "The app store ID of the app, present when the app is linked to a store.",
            "linked_app_info_display_name": "The display name of the app as it appears in the app store.",
        },
    },
    "ad_units": {
        "description": "The ad units of the AdMob account.",
        "docs_url": "https://developers.google.com/admob/api/v1/reference/rest/v1/accounts.adUnits/list",
        "columns": {
            "name": "Resource name of the ad unit, in the format accounts/{publisher_id}/adUnits/{ad_unit_id_fragment}.",
            "ad_unit_id": "The externally visible ID of the ad unit, for example ca-app-pub-9876543210987654/0123456789.",
            "app_id": "The externally visible ID of the app this ad unit belongs to.",
            "display_name": "The display name of the ad unit as shown in the AdMob UI.",
            "ad_format": "The format of the ad unit, for example BANNER, INTERSTITIAL, REWARDED or NATIVE.",
            "ad_types": "Ad media types the ad unit supports: RICH_MEDIA, VIDEO or both.",
        },
    },
}
