from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# App Store Connect splits into very different transports, so the catalog carries four kinds:
#
#   - "collection":       a top-level JSON:API list (`/v1/apps`, `/v1/builds`, ...) walked via `links.next`.
#   - "app_fanout":       a per-app JSON:API list (`/v1/apps/{app_id}/customerReviews`, ...). Apps are
#                         discovered from `/v1/apps` first, then each app's collection is walked.
#   - "sales_report":     `/v1/salesReports`, which is not a collection at all — one request per report date
#                         returns a gzipped TSV file. Walked forward a day at a time from the watermark.
#   - "analytics_report": Apple's Analytics Reports API, an asynchronous request/poll/download flow.
#                         Per app: ensure an ONGOING report request exists (the one account mutation this
#                         source makes), find the named report under it, list its DAILY instances, then
#                         download and parse each instance's file segments. Walked forward by instance
#                         processing date from the watermark.
EndpointKind = Literal["collection", "app_fanout", "sales_report", "analytics_report"]

# Apple caps most collection pages at 200 resources.
MAX_PAGE_SIZE = 200

# Daily sales/subscription reports are only retained for about a year, so a first sync walks back this
# far rather than to the App Store's launch. Each day is one request, so this also bounds the backfill.
SALES_REPORT_LOOKBACK_DAYS = 365

# Days of reports fetched in a single run. A run that hits the cap resumes from its bookmark next time,
# which keeps a cold-start backfill inside the hourly request budget (~3,500 requests per key).
SALES_REPORT_MAX_DAYS_PER_RUN = 400

# Reports for a given day only publish once Apple closes it out, so the newest date we ask for is
# yesterday (UTC). Asking for today reliably 404s.
SALES_REPORT_END_OFFSET_DAYS = 1

# Analytics reports generate one instance per day per granularity; only DAILY is synced. Weekly and
# monthly instances aggregate the same rows, so syncing them too would double-count.
ANALYTICS_GRANULARITY = "DAILY"

# Analytics instances downloaded in a single run, across all apps. Ongoing requests accumulate at
# most ~35 daily instances (Apple's retention) per report per app, so this cap only bites on a
# cold start with many apps. The walk is date-ascending, so an incremental sync that hits the cap
# continues from its watermark next run; a full-refresh sync has no watermark and stays truncated
# until its backlog fits in one run.
ANALYTICS_MAX_INSTANCES_PER_RUN = 400


@dataclass
class AppStoreConnectEndpointConfig:
    name: str
    kind: EndpointKind
    primary_keys: list[str]
    # JSON:API path. `app_fanout` paths carry a single `{app_id}` placeholder.
    path: str = ""
    # Extra query params. Only set `sort` where Apple documents the value for that specific resource —
    # an unsupported sort is a hard 400, and every collection here is a full refresh merged on a unique
    # primary key, so page order doesn't affect correctness.
    params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-style field to partition by — never an updated/modified field.
    partition_key: Optional[str] = None
    should_sync_default: bool = True
    # When set, rows for this endpoint come from the pages' JSON:API `included` resources
    # of this type (requested via an `include` param) instead of `data`. Lets a related
    # resource with no list endpoint of its own ride another collection's walk.
    rows_from_included_type: Optional[str] = None
    # Column that carries the id of the `data` resource referencing each included row, so
    # the table joins back to its parent without a per-row request.
    included_parent_column: str = "parent_id"
    # Analytics Reports API selectors, only meaningful for the "analytics_report" kind.
    # Acceptable report names in preference order: Apple exposes most reports as separate
    # "<name> Standard" / "<name> Detailed" resources, but a few (App Crashes, App Clip
    # Usage) carry no suffix on their standard variant. Standard is preferred: it covers
    # the full population, while Detailed is limited to opted-in users.
    analytics_report_names: tuple[str, ...] = ()
    # Category the report lives under, sent as filter[category] so the per-request report
    # list stays one page.
    analytics_report_category: str = ""
    # `/v1/salesReports` filters, only meaningful for the "sales_report" kind.
    report_type: str = ""
    report_sub_type: str = ""
    # Apple versions each report layout independently; these are the current documented versions for
    # the DAILY/SUMMARY combination of each report type.
    report_version: str = ""
    report_frequency: str = "DAILY"
    # Apple 404s a SALES report request for a date with no data. Subscription-family report types
    # (SUBSCRIPTION, SUBSCRIPTION_EVENT) instead 400 with a misleading "Invalid vendor number
    # specified" error for that same condition — a longstanding, publicly reported Apple API quirk,
    # not an actual credentials problem. Treat both as "no report for this day" for those types.
    missing_report_status_codes: tuple[int, ...] = (404,)


_REPORT_DATE_FIELD: IncrementalField = incremental_field("report_date", IncrementalFieldType.Date)

_PROCESSING_DATE_FIELD: IncrementalField = incremental_field("processing_date", IncrementalFieldType.Date)


def _analytics_endpoint(name: str, report_names: tuple[str, ...], category: str) -> AppStoreConnectEndpointConfig:
    # All analytics report streams share their shape: keyed on (app, instance processing
    # date, line in the instance's files), because an instance's rows may restate earlier
    # data dates and each instance is immutable once its files publish. Off by default:
    # enabling the first stream creates a report request on the customer's account, and
    # the row volume is substantial.
    return AppStoreConnectEndpointConfig(
        name=name,
        kind="analytics_report",
        primary_keys=["app_id", "processing_date", "_line"],
        analytics_report_names=report_names,
        analytics_report_category=category,
        incremental_fields=[_PROCESSING_DATE_FIELD],
        partition_key="processing_date",
        should_sync_default=False,
    )


APP_STORE_CONNECT_ENDPOINTS: dict[str, AppStoreConnectEndpointConfig] = {
    # The app inventory, and the parent every fan-out endpoint iterates. App attributes carry no
    # timestamp, so there is nothing to partition on.
    "apps": AppStoreConnectEndpointConfig(
        name="apps",
        kind="collection",
        primary_keys=["id"],
        path="/v1/apps",
    ),
    # Every version record per app — release type, review state, release dates.
    "app_store_versions": AppStoreConnectEndpointConfig(
        name="app_store_versions",
        kind="app_fanout",
        primary_keys=["app_id", "id"],
        path="/v1/apps/{app_id}/appStoreVersions",
        partition_key="createdDate",
    ),
    # Uploaded builds across the account. `uploadedDate` is a documented sort value here.
    "builds": AppStoreConnectEndpointConfig(
        name="builds",
        kind="collection",
        primary_keys=["id"],
        path="/v1/builds",
        params={"sort": "uploadedDate"},
        partition_key="uploadedDate",
    ),
    # TestFlight groups.
    "beta_groups": AppStoreConnectEndpointConfig(
        name="beta_groups",
        kind="collection",
        primary_keys=["id"],
        path="/v1/betaGroups",
        partition_key="createdDate",
    ),
    # Reviews and ratings per app. Apple exposes `sort=createdDate` but no `createdDate` filter, so an
    # "incremental" sync would still have to walk every page — this stays a full refresh.
    "customer_reviews": AppStoreConnectEndpointConfig(
        name="customer_reviews",
        kind="app_fanout",
        primary_keys=["app_id", "id"],
        path="/v1/apps/{app_id}/customerReviews",
        params={"sort": "createdDate"},
        partition_key="createdDate",
    ),
    # Developer responses to customer reviews: the other half of the reviews conversation.
    # Responses have no list endpoint of their own, so they ride the per-app reviews walk
    # via `include=response`, filtered to reviews with a published response so unresponded
    # reviews are never paged through. Rows come from the pages' included resources, each
    # carrying the id of the review it answers. The only timestamp on a response is
    # lastModifiedDate, which changes when the response is edited, so the table is
    # unpartitioned (partition keys must never change for a row). Full refresh replaces
    # the table each sync, so edited responses update and deleted ones drop out.
    "review_responses": AppStoreConnectEndpointConfig(
        name="review_responses",
        kind="app_fanout",
        primary_keys=["app_id", "id"],
        path="/v1/apps/{app_id}/customerReviews",
        params={"include": "response", "exists[publishedResponse]": "true", "sort": "createdDate"},
        rows_from_included_type="customerReviewResponses",
        included_parent_column="review_id",
    ),
    # In-app purchase catalog per app.
    "in_app_purchases": AppStoreConnectEndpointConfig(
        name="in_app_purchases",
        kind="app_fanout",
        primary_keys=["app_id", "id"],
        path="/v1/apps/{app_id}/inAppPurchasesV2",
    ),
    # Subscription groups per app.
    "subscription_groups": AppStoreConnectEndpointConfig(
        name="subscription_groups",
        kind="app_fanout",
        primary_keys=["app_id", "id"],
        path="/v1/apps/{app_id}/subscriptionGroups",
    ),
    # Daily units and proceeds. Off by default because it needs a vendor number and a Finance or Sales
    # role on the key. Keyed on (report date, line number): a published day's file is immutable, so the
    # pair is stable and unique, and re-reading a day merges cleanly.
    "sales_reports": AppStoreConnectEndpointConfig(
        name="sales_reports",
        kind="sales_report",
        primary_keys=["report_date", "_line"],
        report_type="SALES",
        report_sub_type="SUMMARY",
        report_version="1_0",
        incremental_fields=[_REPORT_DATE_FIELD],
        partition_key="report_date",
        should_sync_default=False,
    ),
    # Daily active subscription counts by state and territory.
    "subscription_reports": AppStoreConnectEndpointConfig(
        name="subscription_reports",
        kind="sales_report",
        primary_keys=["report_date", "_line"],
        report_type="SUBSCRIPTION",
        report_sub_type="SUMMARY",
        report_version="1_4",
        incremental_fields=[_REPORT_DATE_FIELD],
        partition_key="report_date",
        should_sync_default=False,
        missing_report_status_codes=(404, 400),
    ),
    # Daily subscription lifecycle events (renewals, cancellations, upgrades).
    "subscription_event_reports": AppStoreConnectEndpointConfig(
        name="subscription_event_reports",
        kind="sales_report",
        primary_keys=["report_date", "_line"],
        report_type="SUBSCRIPTION_EVENT",
        report_sub_type="SUMMARY",
        report_version="1_4",
        incremental_fields=[_REPORT_DATE_FIELD],
        partition_key="report_date",
        should_sync_default=False,
        missing_report_status_codes=(404, 400),
    ),
    # Analytics Reports API streams: the behavioural data (sessions, downloads, installs
    # and deletions, discovery, crashes, pre-orders, App Clips) that has no sales-report
    # equivalent. The suffix-less fallbacks cover Apple renaming a variant; the crashes
    # and App Clip reports carry no "Standard" suffix today, so their plain name leads.
    "analytics_app_sessions": _analytics_endpoint(
        "analytics_app_sessions",
        ("App Sessions Standard", "App Sessions"),
        "APP_USAGE",
    ),
    "analytics_app_store_downloads": _analytics_endpoint(
        "analytics_app_store_downloads",
        ("App Downloads Standard", "App Downloads"),
        "COMMERCE",
    ),
    "analytics_installations_deletions": _analytics_endpoint(
        "analytics_installations_deletions",
        ("App Store Installation and Deletion Standard", "App Store Installation and Deletion"),
        "APP_USAGE",
    ),
    "analytics_discovery_engagement": _analytics_endpoint(
        "analytics_discovery_engagement",
        ("App Store Discovery and Engagement Standard", "App Store Discovery and Engagement"),
        "APP_STORE_ENGAGEMENT",
    ),
    "analytics_app_crashes": _analytics_endpoint(
        "analytics_app_crashes",
        ("App Crashes", "App Crashes Standard"),
        "APP_USAGE",
    ),
    "analytics_app_store_preorders": _analytics_endpoint(
        "analytics_app_store_preorders",
        ("App Store Pre-Orders Standard", "App Store Pre-Orders"),
        "COMMERCE",
    ),
    "analytics_app_clip_usage": _analytics_endpoint(
        "analytics_app_clip_usage",
        ("App Clip Usage", "App Clip Usage Standard"),
        "APP_USAGE",
    ),
    # Detailed siblings of the analytics streams that carry acquisition attribution. Apple
    # publishes each as a separate "<name> Detailed" report — the Standard columns plus the
    # attribution fields (campaign, page_title, source_info) that exist in no Standard
    # report, covering only users who opted in to sharing data. No suffix-less fallback
    # here: the plain name resolves the Standard variant, which would silently fill the
    # table with rows missing the attribution columns.
    "analytics_app_sessions_detailed": _analytics_endpoint(
        "analytics_app_sessions_detailed",
        ("App Sessions Detailed",),
        "APP_USAGE",
    ),
    "analytics_app_store_downloads_detailed": _analytics_endpoint(
        "analytics_app_store_downloads_detailed",
        ("App Downloads Detailed",),
        "COMMERCE",
    ),
    "analytics_installations_deletions_detailed": _analytics_endpoint(
        "analytics_installations_deletions_detailed",
        ("App Store Installation and Deletion Detailed",),
        "APP_USAGE",
    ),
    "analytics_discovery_engagement_detailed": _analytics_endpoint(
        "analytics_discovery_engagement_detailed",
        ("App Store Discovery and Engagement Detailed",),
        "APP_STORE_ENGAGEMENT",
    ),
}

ENDPOINTS = tuple(APP_STORE_CONNECT_ENDPOINTS.keys())

# Endpoints that read `/v1/salesReports` and therefore need a vendor number.
REPORT_ENDPOINTS = tuple(name for name, config in APP_STORE_CONNECT_ENDPOINTS.items() if config.kind == "sales_report")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APP_STORE_CONNECT_ENDPOINTS.items()
}
