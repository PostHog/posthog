from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class NetSuiteEndpointConfig:
    # SuiteQL record (table) name in the NetSuite2.com data source.
    table: str
    # Keyset pagination orders by these columns, so they must be unique across the table.
    primary_keys: tuple[str, ...]
    # `lastmodifieddate`-style columns that SuiteQL can filter on server-side.
    incremental_fields: tuple[str, ...] = ()


ENDPOINT_CONFIGS: dict[str, NetSuiteEndpointConfig] = {
    "account": NetSuiteEndpointConfig(table="account", primary_keys=("id",)),
    "accountingperiod": NetSuiteEndpointConfig(table="accountingperiod", primary_keys=("id",)),
    "classification": NetSuiteEndpointConfig(table="classification", primary_keys=("id",)),
    "contact": NetSuiteEndpointConfig(table="contact", primary_keys=("id",), incremental_fields=("lastmodifieddate",)),
    "currency": NetSuiteEndpointConfig(table="currency", primary_keys=("id",)),
    "customer": NetSuiteEndpointConfig(
        table="customer", primary_keys=("id",), incremental_fields=("lastmodifieddate",)
    ),
    "department": NetSuiteEndpointConfig(table="department", primary_keys=("id",)),
    "employee": NetSuiteEndpointConfig(
        table="employee", primary_keys=("id",), incremental_fields=("lastmodifieddate",)
    ),
    "item": NetSuiteEndpointConfig(table="item", primary_keys=("id",), incremental_fields=("lastmodifieddate",)),
    "location": NetSuiteEndpointConfig(table="location", primary_keys=("id",)),
    "subsidiary": NetSuiteEndpointConfig(table="subsidiary", primary_keys=("id",)),
    "transaction": NetSuiteEndpointConfig(
        table="transaction", primary_keys=("id",), incremental_fields=("lastmodifieddate",)
    ),
    # Line ids restart at 0 for every transaction, so the parent transaction is part of the key.
    "transactionaccountingline": NetSuiteEndpointConfig(
        table="transactionaccountingline", primary_keys=("transaction", "transactionline", "accountingbook")
    ),
    "transactionline": NetSuiteEndpointConfig(table="transactionline", primary_keys=("transaction", "id")),
    "vendor": NetSuiteEndpointConfig(table="vendor", primary_keys=("id",), incremental_fields=("lastmodifieddate",)),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": field,
            "type": IncrementalFieldType.DateTime,
            "field": field,
            "field_type": IncrementalFieldType.DateTime,
        }
        for field in config.incremental_fields
    ]
    for name, config in ENDPOINT_CONFIGS.items()
    if config.incremental_fields
}

# SuiteQL returns at most 1,000 rows per page.
PAGE_SIZE = 1000
PARTITION_SIZE = 100_000
