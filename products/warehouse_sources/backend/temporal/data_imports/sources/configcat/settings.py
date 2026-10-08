from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Which parent a fan-out endpoint is queried once per. Everything below a product is addressed by
# GUID only, so the deeper resources are reached by walking products first. `config_environment`
# is the config/environment pair the v2 values endpoint takes, and `tag` is reached by walking a
# product's tags.
ConfigCatParent = Literal["organization", "product", "config", "config_environment", "tag"]


@frozen
class ConfigCatEndpointConfig:
    name: str
    path: str
    # ConfigCat's Public Management API returns a stable GUID per object, but the field name
    # differs per resource (products use `productId`, organizations use `organizationId`), so the
    # primary key is declared per endpoint rather than defaulted.
    primary_keys: list[str]
    # None for a top-level listing fetched in a single request.
    parent: ConfigCatParent | None = None
    # Stable creation timestamp to partition on, where the resource has one.
    partition_key: str | None = None
    sort_mode: SortMode = "asc"


# ConfigCat Public Management API endpoints. Only the audit log is paged and time-filtered; every
# other response is the full collection in one request, so those sync full refresh only.
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
    # Change history. The organization endpoint already covers every product in the organization —
    # `productId` is one of its filters — so the per-product endpoint would only repeat these rows.
    "audit_logs": ConfigCatEndpointConfig(
        name="audit_logs",
        path="/v2/organizations/{organizationId}/auditlogs",
        primary_keys=["organizationId", "auditLogId"],
        parent="organization",
        partition_key="auditLogDateTime",
        # The API documents no ordering for the audit log and returns newest-first in practice. In
        # `desc` the pipeline only commits the watermark once the whole run finishes, which is
        # correct whichever order rows arrive in; `asc` would commit a too-high watermark after the
        # first page and skip everything behind it.
        sort_mode="desc",
    ),
    "organization_members": ConfigCatEndpointConfig(
        name="organization_members",
        path="/v2/organizations/{organizationId}/members",
        # One user can hold more than one role in an organization (an admin is often a billing
        # manager too), and the response lists each role separately, so the role is part of the key.
        primary_keys=["organizationId", "userId", "memberType"],
        parent="organization",
    ),
    "product_members": ConfigCatEndpointConfig(
        name="product_members",
        path="/v1/products/{productId}/members",
        primary_keys=["productId", "userId"],
        parent="product",
    ),
    # The stale ("zombie") flag report: flags nothing has changed for a while, per environment.
    "stale_flags": ConfigCatEndpointConfig(
        name="stale_flags",
        path="/v1/products/{productId}/staleflags",
        primary_keys=["productId", "configId", "settingId"],
        parent="product",
    ),
    # `tagId` is keyed on its own because ConfigCat addresses a tag by id alone (`/v1/tags/{tagId}`),
    # the same reasoning the config and environment tables key on their own GUID.
    "tags": ConfigCatEndpointConfig(
        name="tags",
        path="/v1/products/{productId}/tags",
        primary_keys=["tagId"],
        parent="product",
    ),
    # The tag -> feature flag junction. A flag carries several tags and a tag several flags, so the
    # tag is part of the key alongside the flag's own config-scoped identity.
    "tag_settings": ConfigCatEndpointConfig(
        name="tag_settings",
        path="/v1/tags/{tagId}/settings",
        primary_keys=["tagId", "configId", "settingId"],
        parent="tag",
    ),
}

ENDPOINTS = tuple(CONFIGCAT_ENDPOINTS.keys())

# Only the audit log takes a server-side time filter (`fromUtcDateTime`). Everything else returns
# its whole collection with no way to bound it, so a "cursor" there would cost a full sync anyway.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "audit_logs": [
        {
            "label": "auditLogDateTime",
            "type": IncrementalFieldType.DateTime,
            "field": "auditLogDateTime",
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
