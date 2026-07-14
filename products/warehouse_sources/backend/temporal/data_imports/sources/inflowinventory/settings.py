from dataclasses import dataclass


@dataclass
class InflowInventoryEndpointConfig:
    name: str
    # API path segment (kebab-case), appended after the company ID. The table name (`name`) uses
    # underscores so it maps to a valid warehouse table.
    path: str
    # inFlow names each entity's ID field after the entity (e.g. `productId`). The same field is
    # the `after` pagination cursor, so we track it once and reuse it as the primary key.
    id_field: str

    @property
    def primary_keys(self) -> list[str]:
        return [self.id_field]


# inFlow Inventory top-level list endpoints. All are full-refresh only: the documented list
# endpoints expose cursor pagination but no reliably ordered server-side timestamp filter, so
# there is no incremental cursor to advance safely (see the implementing-warehouse-sources skill).
INFLOWINVENTORY_ENDPOINTS: dict[str, InflowInventoryEndpointConfig] = {
    "products": InflowInventoryEndpointConfig(name="products", path="products", id_field="productId"),
    "customers": InflowInventoryEndpointConfig(name="customers", path="customers", id_field="customerId"),
    "vendors": InflowInventoryEndpointConfig(name="vendors", path="vendors", id_field="vendorId"),
    "sales_orders": InflowInventoryEndpointConfig(name="sales_orders", path="sales-orders", id_field="salesOrderId"),
    "purchase_orders": InflowInventoryEndpointConfig(
        name="purchase_orders", path="purchase-orders", id_field="purchaseOrderId"
    ),
}

ENDPOINTS = tuple(INFLOWINVENTORY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
