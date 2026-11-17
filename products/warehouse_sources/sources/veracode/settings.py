from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class VeracodeEndpointConfig:
    name: str
    # Path to the resource. Fan-out endpoints carry a `{application_guid}` placeholder that is filled
    # per parent application while iterating.
    path: str
    # Key under `_embedded` that holds the list of rows for this endpoint (Spring HAL envelope).
    embedded_key: str
    incremental_fields: list[IncrementalField]
    # Field to partition by. Must be a STABLE creation timestamp so partitions never rewrite.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["guid"])
    should_sync_default: bool = True
    # Extra query params merged into every request (e.g. the findings `scan_type` selector).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Iterate every application and query this endpoint once per application GUID.
    fan_out_over_applications: bool = False
    # The response is one object per request (no HAL `_embedded` list).
    single_object: bool = False
    # Rows come from an asynchronous Reporting API report: submit it, poll until it completes, then
    # page through it. `path` is the submit endpoint and the report is read from `{path}/{id}`.
    async_report: bool = False
    sort_mode: Literal["asc", "desc"] | None = "asc"


# Max page size. Veracode's appsec endpoints document up to 500 on some resources, but 100 is the
# safe, universally-accepted value, so we page in 100s until per-endpoint caps are curl-verified.
PAGE_SIZE = 100

VERACODE_ENDPOINTS: dict[str, VeracodeEndpointConfig] = {
    # Application portfolio. The only endpoint with a genuine server-side timestamp filter
    # (`modified_after`), so it drives the incremental sync; the fan-out endpoints below re-pull per
    # application.
    "applications": VeracodeEndpointConfig(
        name="applications",
        path="/appsec/v1/applications",
        embedded_key="applications",
        partition_key="created",
        incremental_fields=[
            {
                "label": "modified",
                "type": IncrementalFieldType.DateTime,
                "field": "modified",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Development sandboxes per application. No server-side timestamp filter, so full refresh only.
    "sandboxes": VeracodeEndpointConfig(
        name="sandboxes",
        path="/appsec/v1/applications/{application_guid}/sandboxes",
        embedded_key="sandboxes",
        partition_key="created",
        incremental_fields=[],
        primary_keys=["application_guid", "guid"],
        fan_out_over_applications=True,
    ),
    # Static, dynamic and manual findings per application. SCA findings must be requested on their
    # own (`scan_type=SCA` cannot be combined with other scan types), so they live in a separate
    # endpoint below. `issue_id` is unique only within an application, so the parent GUID is part of
    # the primary key.
    "findings": VeracodeEndpointConfig(
        name="findings",
        path="/appsec/v2/applications/{application_guid}/findings",
        embedded_key="findings",
        incremental_fields=[],
        primary_keys=["application_guid", "issue_id"],
        extra_params={"scan_type": "STATIC,DYNAMIC,MANUAL"},
        fan_out_over_applications=True,
    ),
    "sca_findings": VeracodeEndpointConfig(
        name="sca_findings",
        path="/appsec/v2/applications/{application_guid}/findings",
        embedded_key="findings",
        incremental_fields=[],
        primary_keys=["application_guid", "issue_id"],
        should_sync_default=False,
        extra_params={"scan_type": "SCA"},
        fan_out_over_applications=True,
    ),
    # Veracode's headline per-application result for the latest policy scan: compliance status,
    # Veracode Level and flaw counts by severity. One object per application, keyed by its GUID.
    "summary_report": VeracodeEndpointConfig(
        name="summary_report",
        path="/appsec/v2/applications/{application_guid}/summary_report",
        embedded_key="",
        incremental_fields=[],
        primary_keys=["application_guid"],
        fan_out_over_applications=True,
        single_object=True,
    ),
    # Lookup tables that resolve the CWE and category ids carried on findings rows.
    "cwes": VeracodeEndpointConfig(
        name="cwes",
        path="/appsec/v1/cwes",
        embedded_key="cwes",
        incremental_fields=[],
        primary_keys=["id"],
    ),
    "categories": VeracodeEndpointConfig(
        name="categories",
        path="/appsec/v1/categories",
        embedded_key="categories",
        incremental_fields=[],
        primary_keys=["id"],
    ),
    # Org-wide scan history from the Reporting API v2 Scans report. The Reporting API must be
    # enabled for the account by Veracode support, so the table is off by default. The report
    # order is not documented, so the read makes no sort promise.
    "scans": VeracodeEndpointConfig(
        name="scans",
        path="/analytics/scans/report",
        embedded_key="scans",
        partition_key="submitted",
        incremental_fields=[
            {
                "label": "last_updated_date",
                "type": IncrementalFieldType.Date,
                "field": "last_updated_date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
        # The docs do not say that `scan_id` is unique across applications and scan types.
        primary_keys=["app_id", "scan_id", "scan_type"],
        should_sync_default=False,
        async_report=True,
        sort_mode=None,
    ),
}

ENDPOINTS = tuple(VERACODE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VERACODE_ENDPOINTS.items()
}
