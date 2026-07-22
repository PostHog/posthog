from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

SMARTENGAGE_BASE_URL = "https://api.smartengage.com"


@dataclass
class SmartEngageEndpointConfig:
    name: str
    path: str
    primary_key: list[str]
    # SmartEngage exposes no server-side timestamp filters, so every endpoint is full refresh.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # List endpoints are unpaginated (full collection per response); never sent as a param.
    page_size: int = 0
    fanout: DependentEndpointConfig | None = None


def _avatar_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="avatars",
        resolve_param="avatar_id",
        resolve_field="avatar_id",
        include_from_parent=["avatar_id"],
        parent_field_renames={"avatar_id": "avatar_id"},
    )


SMARTENGAGE_ENDPOINTS: dict[str, SmartEngageEndpointConfig] = {
    "avatars": SmartEngageEndpointConfig(
        name="avatars",
        path="/avatars/list",
        primary_key=["avatar_id"],
    ),
    # The per-avatar list endpoints take avatar_id as a query param, but the rest_source
    # framework only binds resolve params in the path, so the query string carries the
    # placeholder and is formatted per parent row.
    "tags": SmartEngageEndpointConfig(
        name="tags",
        path="/tags/list?avatar_id={avatar_id}",
        # Tag ids are only documented per avatar and this table aggregates every avatar's
        # tags, so the avatar id is part of the key to keep it unique table-wide.
        primary_key=["avatar_id", "tag_id"],
        fanout=_avatar_fanout(),
    ),
    "custom_fields": SmartEngageEndpointConfig(
        name="custom_fields",
        path="/customfields/list?avatar_id={avatar_id}",
        primary_key=["avatar_id", "custom_field_id"],
        fanout=_avatar_fanout(),
    ),
    "sequences": SmartEngageEndpointConfig(
        name="sequences",
        path="/sequences/list?avatar_id={avatar_id}",
        primary_key=["avatar_id", "sequence_id"],
        fanout=_avatar_fanout(),
    ),
}

ENDPOINTS = tuple(SMARTENGAGE_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTENGAGE_ENDPOINTS.items()
}
