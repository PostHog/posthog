from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# Which parent a fan-out endpoint is queried once per. Everything below a product is addressed by
# GUID only, so the deeper resources are reached by walking products first. `config_environment`
# is the config/environment pair the v2 values endpoint takes.
ConfigCatParent = Literal["product", "config", "config_environment"]


@dataclass
class ConfigCatEndpointConfig:
    name: str
    path: str
    # ConfigCat's Public Management API returns a stable GUID per object, but the field name
    # differs per resource (products use `productId`, organizations use `organizationId`), so the
    # primary key is declared per endpoint rather than defaulted.
    primary_keys: list[str]
    # None for a top-level listing fetched in a single request.
    parent: ConfigCatParent | None = None


# ConfigCat Public Management API endpoints. None of them accept a page, cursor or timestamp
# parameter — every response is the full collection — so sync is full refresh only.
CONFIGCAT_ENDPOINTS: dict[str, ConfigCatEndpointConfig] = {
    "products": ConfigCatEndpointConfig(name="products", path="/v1/products", primary_keys=["productId"]),
    "organizations": ConfigCatEndpointConfig(
        name="organizations", path="/v1/organizations", primary_keys=["organizationId"]
    ),
    "configs": ConfigCatEndpointConfig(
        name="configs",
        path="/v1/products/{productId}/configs",
        primary_keys=["configId"],
        parent="product",
    ),
    "environments": ConfigCatEndpointConfig(
        name="environments",
        path="/v1/products/{productId}/environments",
        primary_keys=["environmentId"],
        parent="product",
    ),
    # The feature flag catalog. `settingId` is an integer the docs only describe as identifying a
    # flag within its config, so the config is part of the key; rows carry `configId` themselves.
    "settings": ConfigCatEndpointConfig(
        name="settings",
        path="/v1/configs/{configId}/settings",
        primary_keys=["configId", "settingId"],
        parent="config",
    ),
    # What each flag currently evaluates to in each environment, with its targeting rules.
    "setting_values": ConfigCatEndpointConfig(
        name="setting_values",
        path="/v2/configs/{configId}/environments/{environmentId}/values",
        primary_keys=["configId", "environmentId", "settingId"],
        parent="config_environment",
    ),
}

ENDPOINTS = tuple(CONFIGCAT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
