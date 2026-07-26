from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# `lastmodifieddate` is stored in the NetSuite account's own time zone, and NetSuite writes it with
# second granularity, so a cursor taken from row values can sit slightly ahead of rows still being
# committed. Every incremental table re-reads a trailing day; the merge dedupes on the primary key.
INCREMENTAL_LOOKBACK_SECONDS = 24 * 60 * 60

_LAST_MODIFIED: list[IncrementalField] = [incremental_field("lastmodifieddate")]
# `transactionline` tracks its own edit timestamp separately from the parent transaction's.
_LINE_LAST_MODIFIED: list[IncrementalField] = [incremental_field("linelastmodifieddate")]


@dataclass
class NetSuiteEndpointConfig:
    """One SuiteQL-queryable NetSuite record type exposed as a warehouse table."""

    name: str
    # SuiteQL table name, used verbatim in `SELECT * FROM <table>`. Never user-supplied.
    table: str
    # Strictly increasing numeric column used for keyset pagination (`WHERE <col> > <last>`).
    # SuiteQL's offset pagination caps out at 100,000 rows without SuiteAnalytics Connect, so
    # keyset paging is the only way to walk a large NetSuite table to completion.
    keyset_column: str = "id"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time column to partition on — never a last-modified column, which would
    # move rows between partitions on every edit. `None` disables partitioning.
    partition_key: str | None = None


NETSUITE_ENDPOINTS: dict[str, NetSuiteEndpointConfig] = {
    # --- Transactions (the volume tables) ---
    "transactions": NetSuiteEndpointConfig(
        name="transactions",
        table="transaction",
        incremental_fields=_LAST_MODIFIED,
        partition_key="createddate",
    ),
    "transaction_lines": NetSuiteEndpointConfig(
        name="transaction_lines",
        table="transactionline",
        # A transaction line's `id` is only unique within its parent transaction; `uniquekey` is the
        # table-wide key, so it is both the primary key and the keyset cursor.
        keyset_column="uniquekey",
        primary_keys=["uniquekey"],
        incremental_fields=_LINE_LAST_MODIFIED,
    ),
    # --- Entities ---
    "customers": NetSuiteEndpointConfig(
        name="customers",
        table="customer",
        incremental_fields=_LAST_MODIFIED,
        partition_key="datecreated",
    ),
    "vendors": NetSuiteEndpointConfig(
        name="vendors",
        table="vendor",
        incremental_fields=_LAST_MODIFIED,
        partition_key="datecreated",
    ),
    "employees": NetSuiteEndpointConfig(
        name="employees",
        table="employee",
        incremental_fields=_LAST_MODIFIED,
        partition_key="datecreated",
    ),
    "contacts": NetSuiteEndpointConfig(
        name="contacts",
        table="contact",
        incremental_fields=_LAST_MODIFIED,
        partition_key="datecreated",
    ),
    "jobs": NetSuiteEndpointConfig(
        name="jobs",
        table="job",
        incremental_fields=_LAST_MODIFIED,
        partition_key="datecreated",
    ),
    # --- Catalog ---
    "items": NetSuiteEndpointConfig(name="items", table="item", incremental_fields=_LAST_MODIFIED),
    # --- Setup / dimension tables (small, no last-modified column exposed in SuiteQL) ---
    "accounts": NetSuiteEndpointConfig(name="accounts", table="account"),
    "accounting_periods": NetSuiteEndpointConfig(name="accounting_periods", table="accountingperiod"),
    "subsidiaries": NetSuiteEndpointConfig(name="subsidiaries", table="subsidiary"),
    "departments": NetSuiteEndpointConfig(name="departments", table="department"),
    "locations": NetSuiteEndpointConfig(name="locations", table="location"),
    "classifications": NetSuiteEndpointConfig(name="classifications", table="classification"),
    "currencies": NetSuiteEndpointConfig(name="currencies", table="currency"),
}

ENDPOINTS = tuple(NETSUITE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in NETSUITE_ENDPOINTS.items()
}
