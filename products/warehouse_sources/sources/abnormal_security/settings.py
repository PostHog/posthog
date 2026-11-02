from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field

API_DOCS_URL = "https://app.swaggerhub.com/apis-docs/abnormal-security/abx/1.5.0"
REGION_HOSTS = {
    "us": "https://api.abnormalplatform.com",
    "eu": "https://eu.rest.abnormalsecurity.com",
}


@frozen
class AbnormalEndpoint:
    path: str
    selector: str
    primary_key: str
    filter_field: str
    incremental_field: str | None = None
    partition_key: str | None = None
    detail_path: str | None = None


ENDPOINTS = {
    "threats": AbnormalEndpoint(
        path="threats",
        selector="threats",
        primary_key="threatId",
        filter_field="receivedTime",
        detail_path="threats/{id}",
    ),
    "cases": AbnormalEndpoint(
        path="cases",
        selector="cases",
        primary_key="caseId",
        filter_field="lastModifiedTime",
        incremental_field="last_modified",
        partition_key="created",
    ),
    "vendor_cases": AbnormalEndpoint(
        path="vendor-cases",
        selector="vendorCases",
        primary_key="vendorCaseId",
        filter_field="lastModifiedTime",
        incremental_field="lastModifiedTime",
        partition_key="firstObservedTime",
        detail_path="vendor-cases/{id}",
    ),
}
INCREMENTAL_FIELDS = {
    name: [incremental_field(endpoint.incremental_field)] if endpoint.incremental_field else []
    for name, endpoint in ENDPOINTS.items()
}
