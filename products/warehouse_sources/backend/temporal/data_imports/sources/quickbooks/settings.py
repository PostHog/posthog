from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every QuickBooks Online entity carries a `MetaData` complex type holding `CreateTime` and
# `LastUpdatedTime`. The transport hoists both to the row root so they can drive incremental
# sync and partitioning, which need top-level columns.
METADATA_KEY = "MetaData"
CREATE_TIME_FIELD = "CreateTime"
LAST_UPDATED_FIELD = "LastUpdatedTime"

# Path the query language uses to reach the same timestamp inside WHERE / ORDERBY clauses.
LAST_UPDATED_QUERY_PATH = "Metadata.LastUpdatedTime"

_LAST_UPDATED_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": LAST_UPDATED_FIELD,
        "type": IncrementalFieldType.DateTime,
        "field": LAST_UPDATED_FIELD,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class QuickBooksEntityConfig:
    # QuickBooks entity name, used verbatim as the query `FROM` target and as the key the rows
    # arrive under in `QueryResponse`.
    name: str
    primary_key: str = "Id"
    # `CompanyInfo` and `Preferences` hold exactly one row per company, so they take no
    # WHERE / ORDERBY / pagination clauses and incremental sync would buy nothing.
    singleton: bool = False

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [] if self.singleton else list(_LAST_UPDATED_INCREMENTAL_FIELDS)

    @property
    def partition_key(self) -> str | None:
        return None if self.singleton else CREATE_TIME_FIELD


_SINGLETON_ENTITIES = frozenset({"CompanyInfo", "Preferences"})

# Read-and-queryable accounting entities. Names are the QuickBooks entity names, so a synced
# table reads the same as the entity in Intuit's own API reference.
_ENTITY_NAMES = (
    "Account",
    "Attachable",
    "Bill",
    "BillPayment",
    "Budget",
    "Class",
    "CompanyInfo",
    "CreditMemo",
    "Customer",
    "Department",
    "Deposit",
    "Employee",
    "Estimate",
    "Invoice",
    "Item",
    "JournalEntry",
    "Payment",
    "PaymentMethod",
    "Preferences",
    "Purchase",
    "PurchaseOrder",
    "RefundReceipt",
    "SalesReceipt",
    "TaxCode",
    "TaxRate",
    "Term",
    "TimeActivity",
    "Transfer",
    "Vendor",
    "VendorCredit",
)

QUICKBOOKS_ENTITIES: dict[str, QuickBooksEntityConfig] = {
    name: QuickBooksEntityConfig(name=name, singleton=name in _SINGLETON_ENTITIES) for name in _ENTITY_NAMES
}

ENDPOINTS = tuple(QUICKBOOKS_ENTITIES.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: entity.incremental_fields for name, entity in QUICKBOOKS_ENTITIES.items() if entity.incremental_fields
}
