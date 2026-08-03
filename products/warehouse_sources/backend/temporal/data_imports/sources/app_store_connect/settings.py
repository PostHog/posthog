from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# App Store Connect splits into two very different transports, so the catalog carries three kinds:
#
#   - "collection":   a top-level JSON:API list (`/v1/apps`, `/v1/builds`, ...) walked via `links.next`.
#   - "app_fanout":   a per-app JSON:API list (`/v1/apps/{app_id}/customerReviews`, ...). Apps are
#                     discovered from `/v1/apps` first, then each app's collection is walked.
#   - "sales_report": `/v1/salesReports`, which is not a collection at all — one request per report date
#                     returns a gzipped TSV file. Walked forward a day at a time from the watermark.
EndpointKind = Literal["collection", "app_fanout", "sales_report"]

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
}

ENDPOINTS = tuple(APP_STORE_CONNECT_ENDPOINTS.keys())

# Endpoints that read `/v1/salesReports` and therefore need a vendor number.
REPORT_ENDPOINTS = tuple(name for name, config in APP_STORE_CONNECT_ENDPOINTS.items() if config.kind == "sales_report")

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APP_STORE_CONNECT_ENDPOINTS.items()
}
