from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Aha! caps `per_page` at 200 (default 30). Always request the max to minimise round trips.
PER_PAGE = 200


def _updated_at_incremental_fields() -> list[IncrementalField]:
    # Every incremental-capable Aha! Ideas endpoint filters server-side with `updated_since`,
    # which keys off `updated_at`. Advertising just `updated_at` keeps the user's chosen cursor
    # aligned with what the API actually filters on.
    return [
        {
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field": "updated_at",
            "field_type": IncrementalFieldType.DateTime,
        },
    ]


@dataclass
class AhaIdeasEndpointConfig:
    name: str
    path: str  # Path under /api/v1, e.g. "/ideas"
    # Root key of the list in the JSON response. Usually equals `path` minus the slash, but
    # `/ideas/endorsements` exposes idea votes under an `idea_endorsements` root key.
    response_key: str
    # Aha! exposes `updated_since` (filters by `updated_at`) on this endpoint's list action.
    supports_incremental: bool
    # Stable creation-time field to partition by. None when the resource has no reliable created_at.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    page_size: int = PER_PAGE
    fanout: DependentEndpointConfig | None = None


AHA_IDEAS_ENDPOINTS: dict[str, AhaIdeasEndpointConfig] = {
    "ideas": AhaIdeasEndpointConfig(
        name="ideas",
        path="/ideas",
        response_key="ideas",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "idea_portals": AhaIdeasEndpointConfig(
        name="idea_portals",
        path="/idea_portals",
        response_key="idea_portals",
        # "List all idea portals in an account" documents only `page`/`per_page` — no
        # `updated_since` filter — so this stays full refresh.
        supports_incremental=False,
    ),
    "idea_organizations": AhaIdeasEndpointConfig(
        name="idea_organizations",
        path="/idea_organizations",
        response_key="idea_organizations",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "idea_users": AhaIdeasEndpointConfig(
        name="idea_users",
        path="/idea_users",
        response_key="idea_users",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "idea_themes": AhaIdeasEndpointConfig(
        name="idea_themes",
        path="/idea_themes",
        response_key="idea_themes",
        # "List idea themes" documents only `page`/`per_page` — no `updated_since` filter.
        supports_incremental=False,
    ),
    "idea_endorsements": AhaIdeasEndpointConfig(
        name="idea_endorsements",
        path="/ideas/endorsements",
        response_key="idea_endorsements",
        supports_incremental=True,
        incremental_fields=_updated_at_incremental_fields(),
    ),
    "idea_comments": AhaIdeasEndpointConfig(
        name="idea_comments",
        path="/ideas/{idea_id}/idea_comments",
        response_key="idea_comments",
        # "List idea comments for an idea" documents only `page`/`per_page`/`idea_id` — no
        # `updated_since` filter.
        supports_incremental=False,
        # Aha!'s comment ids already look globally unique, but the parent idea id is included
        # defensively since this table aggregates comments fanned out across every idea and the
        # docs don't explicitly state global uniqueness.
        primary_keys=["id", "idea_id"],
        fanout=DependentEndpointConfig(
            parent_name="ideas",
            resolve_param="idea_id",
            resolve_field="id",
            # The idea_comments response already includes `idea_id` on every row natively, so no
            # parent fields need to be injected.
            include_from_parent=[],
        ),
    ),
}

ENDPOINTS = tuple(AHA_IDEAS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AHA_IDEAS_ENDPOINTS.items()
}
