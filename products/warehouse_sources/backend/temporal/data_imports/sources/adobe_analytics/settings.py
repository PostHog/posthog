from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The reporting stream is the one endpoint that is a query rather than a listing, so it is
# routed separately from the metadata catalog endpoints.
REPORT_ENDPOINT = "report"

# Adobe's paginated metadata endpoints cap `limit` at 1000.
METADATA_PAGE_SIZE = 1000
# `/reports` defaults to 50 rows per page; 400 keeps each request comfortably under the 60s timeout.
REPORT_PAGE_SIZE = 400

DEFAULT_REPORT_DIMENSION = "variables/daterangeday"
DEFAULT_REPORT_METRICS = "metrics/visits,metrics/visitors,metrics/pageviews"

ANNOTATION_EXPANSIONS = (
    "name",
    "description",
    "dateRange",
    "color",
    "applyToAllReports",
    "scope",
    "createdDate",
    "modifiedDate",
    "modifiedById",
    "tags",
    "shares",
    "approved",
    "owner",
    "companyId",
    "reportSuiteName",
    "rsid",
)


@dataclass(frozen=True)
class AdobeAnalyticsEndpointConfig:
    name: str
    # Path under https://analytics.adobe.io/api/{globalCompanyId}
    path: str
    primary_key: list[str]
    # Key the rows live under in a paginated response body. `None` means the endpoint
    # returns a bare JSON array in a single response (no pagination).
    data_key: Optional[str] = None
    # Query param used to scope the request to the configured report suite, if any.
    report_suite_param: Optional[str] = None
    extra_params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)


ADOBE_ANALYTICS_ENDPOINTS: dict[str, AdobeAnalyticsEndpointConfig] = {
    "report_suites": AdobeAnalyticsEndpointConfig(
        name="report_suites",
        path="/collections/suites",
        primary_key=["rsid"],
        data_key="content",
    ),
    "segments": AdobeAnalyticsEndpointConfig(
        name="segments",
        path="/segments",
        primary_key=["id"],
        data_key="content",
        report_suite_param="rsids",
    ),
    "calculated_metrics": AdobeAnalyticsEndpointConfig(
        name="calculated_metrics",
        path="/calculatedmetrics",
        primary_key=["id"],
        data_key="content",
        report_suite_param="rsids",
    ),
    "dimensions": AdobeAnalyticsEndpointConfig(
        name="dimensions",
        path="/dimensions",
        primary_key=["rsid", "id"],
        report_suite_param="rsid",
    ),
    "metrics": AdobeAnalyticsEndpointConfig(
        name="metrics",
        path="/metrics",
        primary_key=["rsid", "id"],
        report_suite_param="rsid",
    ),
    "users": AdobeAnalyticsEndpointConfig(
        name="users",
        path="/users",
        primary_key=["loginId"],
        data_key="content",
    ),
    "annotations": AdobeAnalyticsEndpointConfig(
        name="annotations",
        path="/annotations",
        primary_key=["id"],
        data_key="content",
        extra_params={
            # Without `expansion` Adobe returns only the annotation id, and without `includeType`
            # only annotations the technical account itself owns.
            "expansion": ",".join(ANNOTATION_EXPANSIONS),
            "includeType": "all",
        },
    ),
    REPORT_ENDPOINT: AdobeAnalyticsEndpointConfig(
        name=REPORT_ENDPOINT,
        path="/reports",
        # One row per (report suite, day, dimension item) — the dimension item id is only
        # unique inside its own day's report.
        primary_key=["rsid", "date", "item_id"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
}

ENDPOINTS = tuple(ADOBE_ANALYTICS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ADOBE_ANALYTICS_ENDPOINTS.items() if config.incremental_fields
}
