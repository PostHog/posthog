from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import PaginatorConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.turso.tech"


@frozen
class TursoEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: list[str] | None
    description: str
    params: dict[str, str | int] = field(default_factory=dict)
    paginator: PaginatorConfig = "single_page"
    partition_key: str | None = None
    sort_mode: SortMode | None = None
    should_sync_default: bool = True
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    page_size: int = 100
    fanout: DependentEndpointConfig | None = None


ENDPOINTS: dict[str, TursoEndpointConfig] = {
    "databases": TursoEndpointConfig(
        name="databases",
        path="/v1/organizations/{organization}/databases",
        data_selector="databases",
        primary_keys=["DbId"],
        description="Database metadata, placement, and access settings.",
    ),
    "groups": TursoEndpointConfig(
        name="groups",
        path="/v1/organizations/{organization}/groups",
        data_selector="groups",
        primary_keys=["uuid"],
        description="Database groups and their primary locations.",
    ),
    "members": TursoEndpointConfig(
        name="members",
        path="/v1/organizations/{organization}/members",
        data_selector="members",
        primary_keys=["username"],
        description="Organization members and their roles.",
    ),
    "invites": TursoEndpointConfig(
        name="invites",
        path="/v2/organizations/{organization}/invites",
        data_selector="invites",
        primary_keys=["id"],
        partition_key="created_at",
        description="Pending organization invitations.",
    ),
    "invoices": TursoEndpointConfig(
        name="invoices",
        path="/v1/organizations/{organization}/invoices",
        data_selector="invoices",
        primary_keys=["invoice_number"],
        params={"type": "issued"},
        description="Issued invoices and their payment status.",
    ),
    "audit_logs": TursoEndpointConfig(
        name="audit_logs",
        path="/v1/organizations/{organization}/audit-logs",
        data_selector="audit_logs",
        # The API exposes no unique event ID; a composite key could discard distinct actions.
        primary_keys=None,
        partition_key="created_at",
        sort_mode="desc",
        params={"page_size": 100},
        paginator=PageNumberPaginator(base_page=1, total_path="pagination.total_pages"),
        should_sync_default=False,
        description="Organization activity. Requires the Scaler plan or higher; enable this table to sync it.",
    ),
    "database_usage": TursoEndpointConfig(
        name="database_usage",
        path="/v1/organizations/{organization}/databases/{database_name}/usage",
        data_selector="database",
        primary_keys=["database_id"],
        description="Current calendar month usage totals and instance metrics for each database.",
        fanout=DependentEndpointConfig(
            parent_name="databases",
            resolve_param="database_name",
            resolve_field="encoded_name",
            include_from_parent=["DbId", "Name"],
            parent_field_renames={"DbId": "database_id", "Name": "database_name"},
        ),
    ),
}
