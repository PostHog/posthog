from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AvaTax's OData-style list endpoints cap $top at 1000 records per page.
PAGE_SIZE = 500


def _modified_date_incremental_fields() -> list[IncrementalField]:
    # AvaTax stamps every model with `modifiedDate`/`createdDate`, and its list endpoints filter
    # server-side on any field via `$filter` (see the OData filtering guide), so `modifiedDate` is a
    # reliable, generic incremental cursor across every endpoint below.
    return [
        {
            "label": "modifiedDate",
            "type": IncrementalFieldType.DateTime,
            "field": "modifiedDate",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass(frozen=False)
class AvalaraEndpointConfig:
    name: str
    path: str  # Path under the environment base URL, e.g. "/api/v2/companies".
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=_modified_date_incremental_fields)
    default_incremental_field: Optional[str] = "modifiedDate"
    partition_key: Optional[str] = "createdDate"
    page_size: int = PAGE_SIZE
    fanout: Optional[DependentEndpointConfig] = None


AVALARA_ENDPOINTS: dict[str, AvalaraEndpointConfig] = {
    "Companies": AvalaraEndpointConfig(
        name="Companies",
        path="/api/v2/companies",
    ),
    "Transactions": AvalaraEndpointConfig(
        name="Transactions",
        path="/api/v2/companies/{companyCode}/transactions",
        # GetTransactionByID (`/api/v2/transactions/{id}`) addresses a transaction by `id` alone,
        # with no company scoping, so ids are unique account-wide.
        primary_keys=["id"],
        fanout=DependentEndpointConfig(
            parent_name="Companies",
            resolve_param="companyCode",
            resolve_field="companyCode",
            include_from_parent=[],
        ),
    ),
    "Nexus": AvalaraEndpointConfig(
        name="Nexus",
        path="/api/v2/companies/{companyId}/nexus",
        # Nexus records are only addressable within their owning company (no account-wide lookup),
        # and the row already carries `companyId`, so key on both to stay unique table-wide.
        primary_keys=["id", "companyId"],
        fanout=DependentEndpointConfig(
            parent_name="Companies",
            resolve_param="companyId",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    "Customers": AvalaraEndpointConfig(
        name="Customers",
        path="/api/v2/companies/{companyId}/customers",
        primary_keys=["id", "companyId"],
        fanout=DependentEndpointConfig(
            parent_name="Companies",
            resolve_param="companyId",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    "ExemptionCertificates": AvalaraEndpointConfig(
        name="ExemptionCertificates",
        path="/api/v2/companies/{companyId}/certificates",
        primary_keys=["id", "companyId"],
        fanout=DependentEndpointConfig(
            parent_name="Companies",
            resolve_param="companyId",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
}

ENDPOINTS = tuple(AVALARA_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AVALARA_ENDPOINTS.items()
}
