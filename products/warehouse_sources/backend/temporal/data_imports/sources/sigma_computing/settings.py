from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Sigma's list endpoints default `limit` to 50 and cap it at 1000; always ask for the max to
# minimize round trips per sync.
PAGE_SIZE = 1000

# A Sigma org's cloud deployment is chosen when the org is created and can never be migrated, so
# the host is a fixed, non-secret enum rather than free text.
# https://help.sigmacomputing.com/docs/region-warehouse-and-feature-support
REGION_HOSTS: dict[str, str] = {
    "gcp_us": "api.sigmacomputing.com",
    "gcp_sa": "api.sa.gcp.sigmacomputing.com",
    "aws_us_west": "aws-api.sigmacomputing.com",
    "aws_us_east": "api.us-a.aws.sigmacomputing.com",
    "aws_ca": "api.ca.aws.sigmacomputing.com",
    "aws_eu": "api.eu.aws.sigmacomputing.com",
    "aws_au": "api.au.aws.sigmacomputing.com",
    "aws_uk": "api.uk.aws.sigmacomputing.com",
    "azure_us": "api.us.azure.sigmacomputing.com",
    "azure_eu": "api.eu.azure.sigmacomputing.com",
    "azure_ca": "api.ca.azure.sigmacomputing.com",
    "azure_uk": "api.uk.azure.sigmacomputing.com",
    "azure_au": "api.au.azure.sigmacomputing.com",
}

DEFAULT_REGION = "gcp_us"


def resolve_base_url(region: str) -> str:
    host = REGION_HOSTS.get(region)
    if host is None:
        raise ValueError(f"Unknown Sigma Computing deployment region: {region}")
    return f"https://{host}"


# Shared by every workbook-scoped child endpoint: the parent's `workbookId` is injected under
# `_Workbooks_workbookId` by the fan-out framework, then renamed back to the bare `workbookId` so
# it lines up with each child's composite primary key.
WORKBOOK_FANOUT = DependentEndpointConfig(
    parent_name="Workbooks",
    resolve_param="workbookId",
    resolve_field="workbookId",
    include_from_parent=["workbookId"],
    parent_field_renames={"workbookId": "workbookId"},
)


@frozen
class SigmaComputingEndpointConfig:
    name: str
    path: str
    primary_key: str | list[str]
    # Elements/pages/queries are workbook-scoped sub-resources with no created/updated
    # timestamp of their own, so they carry no partition key.
    partition_key: str | None = "createdAt"
    page_size: int = PAGE_SIZE
    # Sigma's list endpoints expose no server-side updated-since filter, so every table below
    # is full refresh only; these two fields exist only to satisfy the fan-out helper's protocol.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


SIGMA_ENDPOINTS: dict[str, SigmaComputingEndpointConfig] = {
    "Workbooks": SigmaComputingEndpointConfig(
        name="Workbooks",
        path="/v2/workbooks",
        primary_key="workbookId",
    ),
    # Sigma deprecated creating/editing Datasets in favor of Data models on June 2, 2026; Data
    # models is the actively maintained equivalent going forward, so it's the table shipped here
    # instead of the legacy /v2/datasets endpoint.
    "DataModels": SigmaComputingEndpointConfig(
        name="DataModels",
        path="/v2/dataModels",
        primary_key="dataModelId",
    ),
    "Connections": SigmaComputingEndpointConfig(
        name="Connections",
        path="/v2/connections",
        primary_key="connectionId",
    ),
    "Teams": SigmaComputingEndpointConfig(
        name="Teams",
        path="/v2/teams",
        primary_key="teamId",
    ),
    "Members": SigmaComputingEndpointConfig(
        name="Members",
        path="/v2/members",
        primary_key="memberId",
    ),
    "Workspaces": SigmaComputingEndpointConfig(
        name="Workspaces",
        path="/v2/workspaces",
        primary_key="workspaceId",
    ),
    "Reports": SigmaComputingEndpointConfig(
        name="Reports",
        path="/v2/reports",
        primary_key="reportId",
    ),
    "WorkbookElements": SigmaComputingEndpointConfig(
        name="WorkbookElements",
        path="/v2/workbooks/{workbookId}/elements",
        # elementId is only documented unique within its workbook.
        primary_key=["workbookId", "elementId"],
        partition_key=None,
        fanout=WORKBOOK_FANOUT,
    ),
    "WorkbookPages": SigmaComputingEndpointConfig(
        name="WorkbookPages",
        path="/v2/workbooks/{workbookId}/pages",
        primary_key=["workbookId", "pageId"],
        partition_key=None,
        fanout=WORKBOOK_FANOUT,
    ),
    "WorkbookQueries": SigmaComputingEndpointConfig(
        name="WorkbookQueries",
        path="/v2/workbooks/{workbookId}/queries",
        # Entries carry no dedicated query id; elementId is unique per workbook.
        primary_key=["workbookId", "elementId"],
        partition_key=None,
        fanout=WORKBOOK_FANOUT,
    ),
}

ENDPOINTS = tuple(SIGMA_ENDPOINTS)

# None of Sigma's list endpoints document a server-side updated-since filter (only non-date
# filters like isArchived/search/visibility), so every table above is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in SIGMA_ENDPOINTS}
