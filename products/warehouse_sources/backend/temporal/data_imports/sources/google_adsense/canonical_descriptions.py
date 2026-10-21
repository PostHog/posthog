from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.settings import METRIC_DESCRIPTIONS

_REPORTS_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts.reports/generate"
_AD_CLIENTS_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts.adclients/list"
_AD_UNITS_DOCS_URL = (
    "https://developers.google.com/adsense/management/reference/rest/v2/accounts.adclients.adunits/list"
)
_CUSTOM_CHANNELS_DOCS_URL = (
    "https://developers.google.com/adsense/management/reference/rest/v2/accounts.adclients.customchannels/list"
)
_URL_CHANNELS_DOCS_URL = (
    "https://developers.google.com/adsense/management/reference/rest/v2/accounts.adclients.urlchannels/list"
)
_SITES_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts.sites/list"
_ALERTS_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts.alerts/list"
_POLICY_ISSUES_DOCS_URL = (
    "https://developers.google.com/adsense/management/reference/rest/v2/accounts.policyIssues/list"
)
_PAYMENTS_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts.payments/list"
_ACCOUNT_DOCS_URL = "https://developers.google.com/adsense/management/reference/rest/v2/accounts/get"

# Every stats table carries the same twelve metrics (see METRIC_DESCRIPTIONS), plus the
# date and dimension columns it groups by, plus the syncing account.
_DATE_COLUMN = {
    "date": "The day the metrics were recorded, in the account's reporting time zone.",
}

_ACCOUNT_COLUMN = {
    "account": "The resource name of the AdSense account these rows were synced from (e.g. accounts/pub-1234567890).",
}

_CURRENCY_COLUMN = {
    "currency_code": (
        "ISO 4217 code of the currency the money metrics in this row are reported in "
        "(for example USD). One value per row; it applies to estimated_earnings and cost_per_click."
    ),
}


def _reports(description: str, **dimensions: str) -> CanonicalEndpoint:
    return {
        "description": description,
        "docs_url": _REPORTS_DOCS_URL,
        "columns": {**_DATE_COLUMN, **dimensions, **_CURRENCY_COLUMN, **METRIC_DESCRIPTIONS, **_ACCOUNT_COLUMN},
    }


_AD_CLIENT_ID_COLUMN = "Unique ID of the ad client."
_PRODUCT_COLUMNS = {
    "product_code": "Code of the ad client's product, for example AFC or AFS.",
    "product_name": "Localized name of the ad client's product, for example AdSense for Content or AdSense for Search.",
}
_AD_UNIT_COLUMNS = {
    "ad_unit_id": "Unique ID of the ad unit.",
    "ad_unit_name": "Display name of the ad unit.",
    "ad_unit_size_code": "Size code of the ad unit, for example 728x90 or responsive.",
}
_COUNTRY_COLUMNS = {
    "country_code": "CLDR region code of the searcher's country, for example US or FR.",
    "country_name": "Localized name of the searcher's country.",
}
_PLATFORM_TYPE_COLUMNS = {
    "platform_type_code": "Code of the platform type the ad was viewed on, for example Desktop or HighEndMobile.",
    "platform_type_name": "Localized name of the platform type the ad was viewed on.",
}
_DOMAIN_COLUMNS = {
    "domain_code": "Host name the ad was served on.",
    "domain_name": "Localized, IDNA-decoded host name the ad was served on.",
}
_PAGE_URL_COLUMN = "Canonicalized URL of the page the ad was served on. May not exactly match what a given user saw."
_CUSTOM_CHANNEL_COLUMNS = {
    "custom_channel_id": "Unique ID of the custom channel.",
    "custom_channel_name": "Display name of the custom channel.",
}
_URL_CHANNEL_COLUMNS = {
    "url_channel_id": "Unique ID of the URL channel.",
    "url_channel_name": "The URL channel's URI pattern.",
}
_AD_FORMAT_COLUMNS = {
    "ad_format_code": "Code of the ad format, for example ON_PAGE, ANCHOR, or INTERSTITIAL.",
    "ad_format_name": "Localized name of the ad format, for example In-page, Anchor, or Vignette.",
}

_BASE_DESCRIPTIONS: CanonicalDescriptions = {
    "daily_stats": _reports("Daily performance totals for the account."),
    "ad_client_stats": _reports(
        "Daily performance for the account, grouped by ad client.",
        ad_client_id=_AD_CLIENT_ID_COLUMN,
        **_PRODUCT_COLUMNS,
    ),
    "ad_unit_stats": _reports(
        "Daily performance for the account, grouped by ad unit.",
        **_AD_UNIT_COLUMNS,
    ),
    "country_stats": _reports(
        "Daily performance for the account, grouped by the searcher's country.",
        **_COUNTRY_COLUMNS,
    ),
    "platform_stats": _reports(
        "Daily performance for the account, grouped by platform type.",
        **_PLATFORM_TYPE_COLUMNS,
    ),
    "domain_stats": _reports(
        "Daily performance for the account, grouped by the domain the ad was served on.",
        **_DOMAIN_COLUMNS,
    ),
    "page_url_stats": _reports(
        "Daily performance for the account, grouped by page URL. Off by default due to high cardinality.",
        page_url=_PAGE_URL_COLUMN,
    ),
    "custom_channel_stats": _reports(
        "Daily performance for the account, grouped by custom channel.",
        **_CUSTOM_CHANNEL_COLUMNS,
    ),
    "url_channel_stats": _reports(
        "Daily performance for the account, grouped by URL channel.",
        **_URL_CHANNEL_COLUMNS,
    ),
    "ad_format_stats": _reports(
        "Daily performance for the account, grouped by ad format.",
        **_AD_FORMAT_COLUMNS,
    ),
    "account": {
        "description": "The connected AdSense account.",
        "docs_url": _ACCOUNT_DOCS_URL,
        "columns": {
            "name": "Resource name of the account. Format: accounts/pub-[0-9]+.",
            "display_name": "Display name of the account.",
            "create_time": "When the account was created.",
            "premium": "Whether this account is premium. Premium accounts have access to additional spam-related metrics.",
            "state": "State of the account.",
            "pending_tasks": "Outstanding tasks in the account's sign-up process, e.g. billing-profile-creation.",
        },
    },
    "ad_client": {
        "description": "Every ad client on the account.",
        "docs_url": _AD_CLIENTS_DOCS_URL,
        "columns": {
            "name": "The resource name of the ad client.",
            "state": "State of the ad client: READY, GETTING_READY, or REQUIRES_REVIEW.",
        },
    },
    "ad_unit": {
        "description": "Ad units configured under each ad client. Fanned out: fetched once per ad client.",
        "docs_url": _AD_UNITS_DOCS_URL,
        "columns": {"name": "The resource name of the ad unit, including its parent ad client."},
    },
    "custom_channel": {
        "description": "Custom channels configured under each ad client. Fanned out: fetched once per ad client.",
        "docs_url": _CUSTOM_CHANNELS_DOCS_URL,
        "columns": {
            "name": "The resource name of the custom channel.",
            "active": "Whether the custom channel is currently active and collecting data.",
        },
    },
    "url_channel": {
        "description": "URL channels configured under each ad client. Fanned out: fetched once per ad client.",
        "docs_url": _URL_CHANNELS_DOCS_URL,
        "columns": {"name": "The resource name of the URL channel."},
    },
    "site": {
        "description": "Sites registered to the account.",
        "docs_url": _SITES_DOCS_URL,
        "columns": {"name": "The resource name of the site."},
    },
    "alert": {
        "description": "Active alerts on the account.",
        "docs_url": _ALERTS_DOCS_URL,
        "columns": {
            "name": "The resource name of the alert.",
            "severity": "Severity of the alert: INFO, WARNING, or SEVERE.",
            "type": "Machine-readable type identifying the alert.",
        },
    },
    "policy_issue": {
        "description": "Policy issues affecting the account's inventory.",
        "docs_url": _POLICY_ISSUES_DOCS_URL,
        "columns": {"name": "The resource name of the policy issue."},
    },
    "payment": {
        "description": "Payments made or pending on the account.",
        "docs_url": _PAYMENTS_DOCS_URL,
        "columns": {
            "name": "The resource name of the payment.",
            "amount": (
                "The payment amount, stored as the raw API string rather than cast to a "
                "number — currency and formatting live in the string itself. The `unpaid` "
                "row's balance changes daily, so its value will differ between syncs even "
                "though the row itself is not new."
            ),
        },
    },
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = _BASE_DESCRIPTIONS
