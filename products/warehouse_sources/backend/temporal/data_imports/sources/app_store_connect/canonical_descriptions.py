"""Canonical, documentation-sourced descriptions for App Store Connect endpoints and columns.

Sourced from Apple's App Store Connect API reference
(https://developer.apple.com/documentation/appstoreconnectapi). Keyed by the endpoint names in
`settings.py` `APP_STORE_CONNECT_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)

# Columns every analytics report stream shares: the sync's own key columns plus the
# fields Apple includes in every report.
_ANALYTICS_SHARED_COLUMNS: dict[str, str] = {
    "app_id": "Identifier of the app the report belongs to.",
    "processing_date": (
        "Date Apple processed the report instance the row came from. Rows in an instance can carry earlier data dates."
    ),
    "_line": "Position of the row within the report instance's files, unique per app and processing date.",
    "date": "Date the events in the row occurred. The first day of the period for weekly or monthly data.",
    "app_name": "Name of the app as set up in App Store Connect.",
    "app_apple_identifier": "Apple ID of the app.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "An app on the App Store, and the parent of the per-app version, review, purchase and subscription tables.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/app",
        "columns": {
            "id": "Apple's opaque identifier for the app.",
            "type": "JSON:API resource type, always `apps`.",
            "name": "Name of the app as it appears on the App Store.",
            "bundleId": "Bundle ID that uniquely identifies the app to Apple's systems.",
            "sku": "Developer-assigned SKU that also identifies the app in sales and financial reports.",
            "primaryLocale": "Default locale for the app's App Store information.",
            "isOrEverWasMadeForKids": "Whether the app is, or has ever been, part of the Kids category.",
            "subscriptionStatusUrl": "Server URL Apple notifies about subscription status changes.",
            "contentRightsDeclaration": "Whether the app contains, or has rights to use, third-party content.",
            "streamlinedPurchasingEnabled": "Whether streamlined in-app purchasing is enabled for the app.",
        },
    },
    "app_store_versions": {
        "description": "A version of an app submitted to the App Store, with its review and release state.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/appstoreversion",
        "columns": {
            "id": "Apple's opaque identifier for the version.",
            "type": "JSON:API resource type, always `appStoreVersions`.",
            "app_id": "Identifier of the app this version belongs to.",
            "platform": "Platform the version targets, such as IOS, MAC_OS or TV_OS.",
            "versionString": "Version number shown on the App Store, for example `2.4.1`.",
            "appVersionState": "Current state of the version in the submission and review flow.",
            "appStoreState": "Legacy state of the version on the App Store, superseded by appVersionState.",
            "copyright": "Copyright notice displayed on the App Store listing.",
            "reviewType": "Whether the version was submitted for App Store or TestFlight review.",
            "releaseType": "How the version is released once approved: MANUAL, AFTER_APPROVAL or SCHEDULED.",
            "earliestReleaseDate": "Earliest date the version may be released, for scheduled releases.",
            "downloadable": "Whether the version is available for download.",
            "createdDate": "When the version record was created.",
        },
    },
    "builds": {
        "description": "A build uploaded to App Store Connect for TestFlight or App Store release.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/build",
        "columns": {
            "id": "Apple's opaque identifier for the build.",
            "type": "JSON:API resource type, always `builds`.",
            "version": "Build number, unique within its pre-release version.",
            "uploadedDate": "When the build was uploaded to App Store Connect.",
            "expirationDate": "When the build stops being installable by testers.",
            "expired": "Whether the build has passed its expiration date.",
            "minOsVersion": "Minimum OS version the build supports.",
            "lsMinimumSystemVersion": "Minimum macOS version the build supports.",
            "computedMinMacOsVersion": "Minimum macOS version Apple computed for the build.",
            "iconAssetToken": "Token referencing the build's app icon asset.",
            "processingState": "Processing state of the build: PROCESSING, FAILED, INVALID or VALID.",
            "buildAudienceType": "Audience the build is available to, such as INTERNAL_ONLY or APP_STORE_ELIGIBLE.",
            "usesNonExemptEncryption": "Whether the build uses encryption that is not exempt from export rules.",
        },
    },
    "beta_groups": {
        "description": "A TestFlight group of beta testers, internal or external, with its public link settings.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/betagroup",
        "columns": {
            "id": "Apple's opaque identifier for the beta group.",
            "type": "JSON:API resource type, always `betaGroups`.",
            "name": "Name of the beta group.",
            "createdDate": "When the group was created.",
            "isInternalGroup": "Whether the group contains internal testers from your team.",
            "publicLinkEnabled": "Whether a public TestFlight link is enabled for the group.",
            "publicLinkId": "Identifier embedded in the group's public TestFlight link.",
            "publicLink": "Public TestFlight link testers use to join the group.",
            "publicLinkLimitEnabled": "Whether the number of testers joining via the public link is capped.",
            "publicLinkLimit": "Maximum number of testers who may join via the public link.",
            "feedbackEnabled": "Whether testers in the group can send feedback.",
            "hasAccessToAllBuilds": "Whether the group automatically receives every new build.",
        },
    },
    "customer_reviews": {
        "description": "A customer review left on the App Store, including its star rating and territory.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/customerreview",
        "columns": {
            "id": "Apple's opaque identifier for the review.",
            "type": "JSON:API resource type, always `customerReviews`.",
            "app_id": "Identifier of the app the review was left on.",
            "rating": "Star rating the customer gave, from 1 to 5.",
            "title": "Title the customer gave the review.",
            "body": "Body text of the review.",
            "reviewerNickname": "Display name of the customer who left the review.",
            "createdDate": "When the review was submitted.",
            "territory": "App Store territory the review was written in.",
        },
    },
    "review_responses": {
        "description": "A developer response published to a customer review, one row per responded review.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/customerreviewresponsev1",
        "columns": {
            "id": "Apple's opaque identifier for the response.",
            "type": "JSON:API resource type, always `customerReviewResponses`.",
            "app_id": "Identifier of the app the responded review was left on.",
            "review_id": "Identifier of the review this response answers; joins to the customer_reviews table.",
            "responseBody": "Body text of the developer's response.",
            "lastModifiedDate": "When the response was created or last edited.",
            "state": "Publication state of the response, PUBLISHED or PENDING_PUBLISH.",
        },
    },
    "in_app_purchases": {
        "description": "An in-app purchase product configured for an app.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/inapppurchasev2",
        "columns": {
            "id": "Apple's opaque identifier for the in-app purchase.",
            "type": "JSON:API resource type, always `inAppPurchases`.",
            "app_id": "Identifier of the app the product belongs to.",
            "name": "Reference name of the in-app purchase, visible only in App Store Connect.",
            "productId": "Product ID your app uses to request the purchase from the App Store.",
            "inAppPurchaseType": "Kind of product: CONSUMABLE, NON_CONSUMABLE or NON_RENEWING_SUBSCRIPTION.",
            "state": "Review and availability state of the product.",
            "reviewNote": "Note supplied to App Review about the product.",
            "familySharable": "Whether the purchase can be shared through Family Sharing.",
            "contentHosting": "Whether Apple hosts the product's downloadable content.",
        },
    },
    "subscription_groups": {
        "description": "A group of auto-renewable subscriptions within an app that customers can move between.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/subscriptiongroup",
        "columns": {
            "id": "Apple's opaque identifier for the subscription group.",
            "type": "JSON:API resource type, always `subscriptionGroups`.",
            "app_id": "Identifier of the app the group belongs to.",
            "referenceName": "Name of the group, visible only in App Store Connect.",
        },
    },
    "sales_reports": {
        "description": "One row of Apple's daily Sales and Trends summary report: units and developer proceeds per SKU, territory and product type.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/download_sales_and_trends_reports",
        "columns": {
            "report_date": "Date the report covers.",
            "_line": "1-based line number within that date's report file, used with report_date as the row key.",
            "provider": "Provider of the content, normally `APPLE`.",
            "provider_country": "Country of the provider.",
            "sku": "SKU of the app or in-app purchase the row covers.",
            "developer": "Name of the developer credited for the sale.",
            "title": "Name of the app the row covers.",
            "version": "Version of the app the transaction applied to.",
            "product_type_identifier": "Code describing the transaction type, such as a first download, update or in-app purchase.",
            "units": "Number of units for this row; negative values are refunds.",
            "developer_proceeds": "Amount paid to you per unit, in the row's currency_of_proceeds. Sum it only within a single currency.",
            "begin_date": "First date covered by the row.",
            "end_date": "Last date covered by the row.",
            "customer_currency": "Currency the customer was charged in.",
            "country_code": "App Store territory the transaction happened in.",
            "currency_of_proceeds": "Currency your proceeds are reported in.",
            "apple_identifier": "Apple's numeric identifier for the app.",
            "customer_price": "Price the customer paid, in the row's customer_currency. Amounts in different currencies are not comparable, so sum this only within a single currency.",
            "promo_code": "Promotional or offer code applied to the transaction.",
            "parent_identifier": "SKU of the parent app for an in-app purchase row.",
            "subscription": "Whether the row relates to a subscription product.",
            "period": "Subscription period the row covers.",
            "category": "App Store category of the app.",
            "cmb": "Whether the transaction came through a carrier-billing arrangement.",
            "device": "Device family the transaction came from.",
            "supported_platforms": "Platforms the app supports.",
            "proceeds_reason": "Reason the applied proceeds rate was used.",
            "preserved_pricing": "Whether legacy preserved pricing applied to the transaction.",
            "client": "Client the purchase was made from, such as the App Store app.",
            "order_type": "Whether the purchase was a normal purchase or a pre-order.",
        },
    },
    "subscription_reports": {
        "description": "One row of Apple's daily Subscription summary report: active, paid and trial subscription counts by state and territory.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/download_sales_and_trends_reports",
        "columns": {
            "report_date": "Date the report covers.",
            "_line": "1-based line number within that date's report file, used with report_date as the row key.",
            "app_name": "Name of the app the subscription belongs to.",
            "app_apple_id": "Apple's numeric identifier for the app.",
            "subscription_name": "Name of the subscription product.",
            "subscription_apple_id": "Apple's numeric identifier for the subscription product.",
            "subscription_group_id": "Identifier of the subscription group the product belongs to.",
            "standard_subscription_duration": "Billing duration of the subscription, such as 1 Month.",
            "promotional_offer_name": "Name of the promotional offer applied, if any.",
            "promotional_offer_id": "Identifier of the promotional offer applied, if any.",
            "customer_price": "Price the customer pays per period, in the row's customer_currency. Amounts in different currencies are not comparable, so sum this only within a single currency.",
            "customer_currency": "Currency the customer is charged in.",
            "developer_proceeds": "Proceeds paid to you per period, in the row's proceeds_currency. Sum it only within a single currency.",
            "proceeds_currency": "Currency your proceeds are reported in.",
            "preserved_pricing": "Whether legacy preserved pricing applies.",
            "proceeds_reason": "Reason the applied proceeds rate was used.",
            "client": "Client the subscription was purchased from.",
            "device": "Device family the subscription was purchased on.",
            "state": "State of the subscription, such as active, in a grace period, or in billing retry.",
            "country": "App Store territory the subscriptions are counted in.",
            "subscribers": "Number of subscribers in this state on the report date.",
        },
    },
    "subscription_event_reports": {
        "description": "One row of Apple's daily Subscription Event report: counts of subscription lifecycle events such as renewals, cancellations and plan changes.",
        "docs_url": "https://developer.apple.com/documentation/appstoreconnectapi/download_sales_and_trends_reports",
        "columns": {
            "report_date": "Date the report covers.",
            "_line": "1-based line number within that date's report file, used with report_date as the row key.",
            "event_date": "Date the events happened.",
            "event": "Lifecycle event counted, such as Subscribe, Renew, Cancel or Reactivate.",
            "app_name": "Name of the app the subscription belongs to.",
            "app_apple_id": "Apple's numeric identifier for the app.",
            "subscription_name": "Name of the subscription product.",
            "subscription_apple_id": "Apple's numeric identifier for the subscription product.",
            "subscription_group_id": "Identifier of the subscription group the product belongs to.",
            "standard_subscription_duration": "Billing duration of the subscription, such as 1 Month.",
            "promotional_offer_name": "Name of the promotional offer involved, if any.",
            "promotional_offer_id": "Identifier of the promotional offer involved, if any.",
            "subscription_offer_type": "Type of offer involved, such as an introductory or promotional offer.",
            "subscription_offer_duration": "Duration of the offer involved.",
            "marketing_opt_in": "Whether the customer opted in to marketing communication.",
            "marketing_opt_in_duration": "Duration of the marketing opt-in offer.",
            "preserved_pricing": "Whether legacy preserved pricing applies.",
            "proceeds_reason": "Reason the applied proceeds rate was used.",
            "consecutive_paid_periods": "Number of consecutive paid periods before the event.",
            "original_start_date": "Date the customer first started the subscription.",
            "client": "Client the event originated from.",
            "device": "Device family the event originated from.",
            "state": "State of the subscription at the time of the event.",
            "previous_subscription_name": "Name of the subscription the customer moved from, for plan changes.",
            "previous_subscription_apple_id": "Identifier of the subscription the customer moved from.",
            "days_before_canceling": "Days between subscribing and cancelling, for cancellation events.",
            "cancellation_reason": "Reason recorded for the cancellation.",
            "days_canceled": "Days the subscription had been cancelled before a reactivation.",
            "quantity": "Number of subscriptions the row counts.",
            "country": "App Store territory the events are counted in.",
        },
    },
    "analytics_app_sessions": {
        "description": (
            "How often people open the app and for how long, from Apple's App Sessions analytics "
            "report. One row per instance line; an instance's rows can restate earlier data dates."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-sessions",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "app_version": "Version of the app in the session.",
            "device": "Device model the sessions occurred on.",
            "platform_version": "OS version of the device.",
            "source_type": "Where the user discovered the app.",
            "page_type": "App Store page associated with the discovery.",
            "app_download_date": "Date the app was downloaded onto the device.",
            "territory": "App Store country or region of the sessions.",
            "sessions": "Total number of sessions.",
            "total_session_duration": "Total duration of the sessions, in seconds.",
            "unique_devices": "Number of unique devices with sessions.",
        },
    },
    "analytics_app_store_downloads": {
        "description": (
            "How many times people download the app on the App Store, including redownloads and "
            "updates, from Apple's App Store Downloads analytics report."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-download",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "download_type": "Kind of download: first-time download, redownload, update, or restore.",
            "app_version": "Version of the app downloaded.",
            "device": "Device model the download occurred on.",
            "platform_version": "OS version of the downloading device.",
            "source_type": "Where the user discovered the app.",
            "page_type": "App Store page the download came from.",
            "pre_order": "Whether the download came from a pre-order.",
            "territory": "App Store country or region of the download.",
            "counts": "Total number of downloads.",
        },
    },
    "analytics_installations_deletions": {
        "description": (
            "How many times users install and delete the app, from Apple's App Store Installations "
            "and Deletions analytics report. Covers users who opted in to sharing data."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-installs",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "event": "Type of event, Install or Delete.",
            "download_type": "How the install originally occurred.",
            "app_version": "Version of the app installed or deleted.",
            "device": "Device model the event occurred on.",
            "platform_version": "OS version of the device.",
            "source_type": "Where the user discovered the app.",
            "page_type": "App Store page that led to the discovery.",
            "app_download_date": "Date the app was downloaded onto the device.",
            "territory": "App Store country or region of the event.",
            "counts": "Total number of events.",
            "unique_devices": "Number of unique devices generating events.",
        },
    },
    "analytics_discovery_engagement": {
        "description": (
            "How users find and interact with the app on the App Store (impressions, page views, "
            "taps), from Apple's App Store Discovery and Engagement analytics report."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-store-discovery-and-engagement",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "event": "Event type: impression, page view, or tap.",
            "page_type": "App Store page associated with the event.",
            "source_type": "Where the user discovered the app.",
            "engagement_type": "Action the user took on the impression or page.",
            "device": "Device model the event occurred on.",
            "platform_version": "OS version of the device.",
            "territory": "App Store country or region of the event.",
            "counts": "Total number of events.",
            "unique_counts": "Number of unique users performing the event.",
        },
    },
    "analytics_app_crashes": {
        "description": (
            "Crash counts by app version and device, from Apple's App Crashes analytics report. "
            "Covers users who opted in to sharing data, with low-volume rows suppressed."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-crashes",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "app_version": "Version of the app that crashed.",
            "device": "Device model the crashes occurred on.",
            "platform_version": "OS version of the device.",
            "crashes": "Total number of crashes.",
            "unique_devices": "Number of unique devices on which the app crashed.",
        },
    },
    "analytics_app_store_preorders": {
        "description": (
            "Pre-orders placed and canceled for the app, from Apple's App Store Pre-orders analytics report."
        ),
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-store-pre-order",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "device": "Device model the pre-order was placed on.",
            "platform_version": "OS version of the device.",
            "source_type": "Where the user discovered the app.",
            "page_type": "App Store page the pre-order was placed from.",
            "territory": "App Store country or region of the pre-order.",
            "pre_order_start_date": "Date the app became available for pre-order.",
            "pre_order_end_date": "Last date the app is available for pre-order.",
            "pre_orders_placed": "Total pre-orders placed.",
            "pre_orders_canceled": "Total pre-orders canceled.",
        },
    },
    "analytics_app_clip_usage": {
        "description": "How users engage with the app's App Clips, from Apple's App Clip Usage analytics report.",
        "docs_url": "https://developer.apple.com/documentation/analytics-reports/app-clip-usage",
        "columns": {
            **_ANALYTICS_SHARED_COLUMNS,
            "app_clip_event_type": "Type of App Clip event: views, installations, sessions, or crashes.",
            "source_type": "Where the user discovered the App Clip.",
            "app_version": "Version of the App Clip on the device.",
            "device": "Device model the event occurred on.",
            "platform_version": "OS version of the device.",
            "territory": "App Store country or region of the event.",
            "counts": "Total number of App Clip events.",
            "total_session_duration": "Total duration of the reported sessions, in seconds.",
            "unique_devices": "Number of unique devices with events.",
        },
    },
}

# The acquisition attribution columns Apple publishes only in Detailed report variants.
_DETAILED_ATTRIBUTION_COLUMNS: dict[str, str] = {
    "campaign": "Campaign token of the App Analytics campaign that led the user to the app.",
    "page_title": "Name of the product page or in-app event page that led the user to the app.",
    "source_info": "App or web referrer that led the user to discover the app; the detail behind source_type.",
}


def _detailed_variant(standard_name: str, description: str) -> CanonicalEndpoint:
    # Apple documents a Detailed report as its Standard sibling's column set plus the
    # attribution columns, on the same docs page, so the entry derives from the sibling
    # rather than restating it.
    standard = CANONICAL_DESCRIPTIONS[standard_name]
    return {
        "description": description,
        "docs_url": standard["docs_url"],
        "columns": {**standard["columns"], **_DETAILED_ATTRIBUTION_COLUMNS},
    }


CANONICAL_DESCRIPTIONS["analytics_app_sessions_detailed"] = _detailed_variant(
    "analytics_app_sessions",
    "How often people open the app and for how long, with the acquisition attribution columns, "
    "from Apple's App Sessions Detailed analytics report.",
)
CANONICAL_DESCRIPTIONS["analytics_app_store_downloads_detailed"] = _detailed_variant(
    "analytics_app_store_downloads",
    "How many times people download the app on the App Store, with the acquisition attribution "
    "columns, from Apple's App Downloads Detailed analytics report.",
)
CANONICAL_DESCRIPTIONS["analytics_installations_deletions_detailed"] = _detailed_variant(
    "analytics_installations_deletions",
    "How many times users install and delete the app, with the acquisition attribution columns, "
    "from Apple's App Store Installation and Deletion Detailed analytics report.",
)
CANONICAL_DESCRIPTIONS["analytics_discovery_engagement_detailed"] = _detailed_variant(
    "analytics_discovery_engagement",
    "How users find and interact with the app on the App Store, with the acquisition attribution "
    "columns, from Apple's App Store Discovery and Engagement Detailed analytics report.",
)
