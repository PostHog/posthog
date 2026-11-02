from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Every Propertyware object carries a global `id` and a `lastModifiedDateTime` audit field
# (verified against the published OpenAPI schema), so pagination, incremental sync, and
# partitioning are uniform across every endpoint below.
PRIMARY_KEY = "id"
INCREMENTAL_FIELD = "lastModifiedDateTime"
# Stable creation timestamp for partitioning; unlike lastModifiedDateTime it never changes once set.
PARTITION_KEY = "createdDateTime"

ENDPOINT_PATHS: dict[str, str] = {
    "Portfolios": "/portfolios",
    "Buildings": "/buildings",
    "Units": "/units",
    "Leases": "/leases",
    "LeaseCharges": "/leases/charges",
    "LeasePayments": "/leases/payments",
    "LeaseAdjustments": "/leases/adjustments",
    "LeaseRefunds": "/leases/refunds",
    "Contacts": "/contacts",
    "Prospects": "/prospects",
    "Vendors": "/vendors",
    "Bills": "/bills",
    "BillPayments": "/bills/payments",
    "WorkOrders": "/workorders",
    "Inspections": "/inspections",
    "GLAccounts": "/accounting/glaccounts",
}

ENDPOINTS: tuple[str, ...] = tuple(ENDPOINT_PATHS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field(INCREMENTAL_FIELD)] for name in ENDPOINTS
}
