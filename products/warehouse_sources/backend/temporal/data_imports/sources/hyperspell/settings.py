from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class HyperspellEndpointConfig:
    name: str
    path: str
    # Key that wraps the list of rows in the JSON response body (e.g. {"items": [...]}).
    data_key: str
    primary_keys: list[str]
    # Endpoints whose data is scoped to a Hyperspell user. When the source is configured with
    # user IDs, these endpoints are fetched once per user via the X-As-User header and every
    # row is stamped with a `user_id` column (empty string when querying as the app).
    user_scoped: bool = False
    # "cursor": returns {..., "next_cursor": "..."} and accepts a `cursor` param.
    # "offset": accepts `offset` and returns a `total` row count. "none": one response.
    pagination: Literal["cursor", "offset", "none"] = "cursor"
    # Query param that controls page size ("size" or "limit", varies per endpoint).
    page_size_param: Optional[str] = "size"
    page_size: int = 100
    # Stable datetime field to partition on. Never use a field that changes after creation.
    partition_key: Optional[str] = None
    # Nullable fields that participate in the primary key, mapped to the value that replaces
    # null so merged/deduped rows keep a non-null key.
    null_key_defaults: dict[str, str] = field(default_factory=dict)


# Hyperspell's list endpoints expose no server-side timestamp filter (the /memories/list
# `filter` param only matches custom metadata), so every endpoint is full refresh only.
HYPERSPELL_ENDPOINTS: dict[str, HyperspellEndpointConfig] = {
    # https://api.hyperspell.com/openapi.json — GET /memories/list
    "memories": HyperspellEndpointConfig(
        name="memories",
        path="/memories/list",
        data_key="items",
        # resource_id is unique per source provider (memories are addressed as
        # /{source}/{resource_id}), and per user when fanning out over users.
        primary_keys=["user_id", "source", "resource_id"],
        user_scoped=True,
        # No partition key: the only stable timestamp (ingested_at) is nullable.
    ),
    # GET /connections/list — not paginated, returns every connection in one response.
    "connections": HyperspellEndpointConfig(
        name="connections",
        path="/connections/list",
        data_key="connections",
        primary_keys=["user_id", "id"],
        user_scoped=True,
        pagination="none",
    ),
    # GET /integrations/list — app-level catalog of available integrations, not paginated.
    "integrations": HyperspellEndpointConfig(
        name="integrations",
        path="/integrations/list",
        data_key="integrations",
        primary_keys=["id"],
        pagination="none",
    ),
    # GET /vault/list — collections of manually added documents.
    "vaults": HyperspellEndpointConfig(
        name="vaults",
        path="/vault/list",
        data_key="items",
        primary_keys=["user_id", "collection"],
        user_scoped=True,
        # A null collection is the user's default vault; keep the key non-null.
        null_key_defaults={"collection": ""},
    ),
    # GET /entities — entities extracted from indexed memories.
    "entities": HyperspellEndpointConfig(
        name="entities",
        path="/entities",
        data_key="items",
        primary_keys=["user_id", "id"],
        user_scoped=True,
        page_size_param="limit",
        page_size=500,  # /entities caps `limit` at 500 (other endpoints cap `size` at 100)
        partition_key="created_at",
    ),
    # GET /evaluate/queries — prior queries issued against the app (rows carry their own
    # user_id, so the listing is app-level and query_id is unique app-wide).
    "queries": HyperspellEndpointConfig(
        name="queries",
        path="/evaluate/queries",
        data_key="items",
        primary_keys=["query_id"],
        partition_key="time",
    ),
    # GET /context-documents — generated context documents for the authenticated app.
    "context_documents": HyperspellEndpointConfig(
        name="context_documents",
        path="/context-documents",
        data_key="documents",
        primary_keys=["document_id"],
        page_size_param="limit",
        partition_key="created_at",
    ),
    # GET /users — the app's users (distinct document owners), app-level and offset paginated.
    "users": HyperspellEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        primary_keys=["user_id"],
        pagination="offset",
        page_size_param="limit",
        page_size=200,  # /users caps `limit` at 200
    ),
    # GET /integrations/{integration_id}/channels?connection_id=... — fanned out over each
    # user's connections whose integration supports channel selection. Channel ids are only
    # unique within a provider workspace, so the connection is part of the key.
    "integration_channels": HyperspellEndpointConfig(
        name="integration_channels",
        path="/integrations/{integration_id}/channels",
        data_key="channels",
        primary_keys=["user_id", "connection_id", "id"],
        user_scoped=True,
        pagination="none",
    ),
}

ENDPOINTS = tuple(HYPERSPELL_ENDPOINTS.keys())

# No endpoint exposes a server-side timestamp filter, so nothing is advertised as incremental.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in HYPERSPELL_ENDPOINTS}
