from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aha! caps `per_page` at 200 (default 30). Always request the max to minimise round trips.
PER_PAGE = 200


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # Aha!'s only server-side time filter is `updated_since`, which keys off `updated_at`.
    # Advertising just `updated_at` keeps the user's chosen cursor aligned with what the API filters on.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class AhaEndpointConfig:
    name: str
    path: str  # Path under /api/v1, e.g. "/features"
    # Root key of the list in the JSON response. Usually equals `path` minus the slash, but Aha!
    # exposes to-dos under `/tasks` with a `tasks` root key, so it's declared explicitly.
    response_key: str
    # Aha! exposes `updated_since` (filters by `updated_at`) on this endpoint's list action.
    supports_incremental: bool
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The cursor field the fan-out helper binds to `updated_since`. Only read for fan-out children.
    default_incremental_field: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Set for child resources that hang off a parent list endpoint (e.g. releases under a product).
    fanout: Optional[DependentEndpointConfig] = None
    # Page size the fan-out helper requests for this resource's list action; matches PER_PAGE.
    page_size: int = PER_PAGE


AHA_ENDPOINTS: dict[str, AhaEndpointConfig] = {
    "products": AhaEndpointConfig(
        name="products",
        path="/products",
        response_key="products",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "features": AhaEndpointConfig(
        name="features",
        path="/features",
        response_key="features",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "epics": AhaEndpointConfig(
        name="epics",
        path="/epics",
        response_key="epics",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "initiatives": AhaEndpointConfig(
        name="initiatives",
        path="/initiatives",
        response_key="initiatives",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "ideas": AhaEndpointConfig(
        name="ideas",
        path="/ideas",
        response_key="ideas",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "goals": AhaEndpointConfig(
        name="goals",
        path="/goals",
        response_key="goals",
        # The Get goals list action documents no `updated_since` filter, so it's full refresh only.
        supports_incremental=False,
    ),
    "todos": AhaEndpointConfig(
        name="todos",
        path="/tasks",
        response_key="tasks",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "users": AhaEndpointConfig(
        name="users",
        path="/users",
        response_key="users",
        # The Get users list action only documents an `email` filter — no time-based incremental.
        supports_incremental=False,
    ),
    # Idea votes are exposed under the `endorsements` path but returned under an `idea_votes`
    # root key (Aha! names the web "votes" as API "endorsements"). The account-wide list action
    # `/ideas/endorsements` supports `updated_since`, so this is a plain top-level endpoint.
    "idea_votes": AhaEndpointConfig(
        name="idea_votes",
        path="/ideas/endorsements",
        response_key="idea_votes",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
        default_incremental_field="updated_at",
    ),
    # Releases have no account-wide list action, only per-product. Fan out over the synced
    # `products` table; `updated_since` filters each product's release list server-side.
    "releases": AhaEndpointConfig(
        name="releases",
        path="/products/{product_id}/releases",
        response_key="releases",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
        default_incremental_field="updated_at",
        # Aha! record ids are globally unique, but keep the parent product id in the key so a
        # duplicate can never span products even if that ever changes.
        primary_keys=["id", "product_id"],
        fanout=DependentEndpointConfig(
            parent_name="products",
            resolve_param="product_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "product_id"},
        ),
    ),
    # Requirements have no account-wide list action, only per-feature. Fan out over the synced
    # `features` table; `updated_since` filters each feature's requirement list server-side.
    "requirements": AhaEndpointConfig(
        name="requirements",
        path="/features/{feature_id}/requirements",
        response_key="requirements",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
        default_incremental_field="updated_at",
        primary_keys=["id", "feature_id"],
        fanout=DependentEndpointConfig(
            parent_name="features",
            resolve_param="feature_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "feature_id"},
        ),
    ),
}

ENDPOINTS = tuple(AHA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AHA_ENDPOINTS.items()
}
