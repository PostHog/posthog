from dataclasses import dataclass


@dataclass
class ConfigCatEndpointConfig:
    name: str
    path: str
    # ConfigCat's Public Management API returns a stable GUID per object, but the field name
    # differs per resource (products use `productId`, organizations use `organizationId`), so the
    # primary key is declared per endpoint rather than defaulted.
    primary_keys: list[str]


# ConfigCat Public Management API top-level list endpoints. Both return a full collection in a
# single response — the API documents no pagination — so sync is full refresh only. The deeper
# resources (configs, environments, settings, values) are hierarchical fan-outs that require a
# parent product id, so they are intentionally excluded from v1.
CONFIGCAT_ENDPOINTS: dict[str, ConfigCatEndpointConfig] = {
    "products": ConfigCatEndpointConfig(name="products", path="/v1/products", primary_keys=["productId"]),
    "organizations": ConfigCatEndpointConfig(
        name="organizations", path="/v1/organizations", primary_keys=["organizationId"]
    ),
}

ENDPOINTS = tuple(CONFIGCAT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
