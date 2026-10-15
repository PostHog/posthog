from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class SecodaEndpointConfig:
    name: str
    path: str
    # Secoda resource identifiers are workspace-unique UUIDs, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Top-level keys removed from every row before it reaches the warehouse.
    drop_fields: tuple[str, ...] = ()


# Secoda v1 REST list endpoints. All are full-refresh only: Secoda's List Resources filter supports
# only exact/contains/in operators (no greater-than / on-or-after), so there is no server-side
# timestamp cursor to advance an incremental sync (see the implementing-warehouse-sources skill).
SECODA_ENDPOINTS: dict[str, SecodaEndpointConfig] = {
    "tables": SecodaEndpointConfig(name="tables", path="/api/v1/table/tables"),
    "columns": SecodaEndpointConfig(name="columns", path="/api/v1/table/columns"),
    "collections": SecodaEndpointConfig(name="collections", path="/api/v1/collection/collections"),
    "users": SecodaEndpointConfig(name="users", path="/api/v1/user"),
    "groups": SecodaEndpointConfig(name="groups", path="/api/v1/auth/group"),
    "tags": SecodaEndpointConfig(name="tags", path="/api/v1/tag"),
    "databases": SecodaEndpointConfig(name="databases", path="/api/v1/database/databases"),
    "schemas": SecodaEndpointConfig(name="schemas", path="/api/v1/database/schemas"),
    # Secoda documents `credentials` as redacted, but a credentials blob has no analytical value and
    # must never land in the warehouse if that redaction ever changes.
    "integrations": SecodaEndpointConfig(
        name="integrations", path="/api/v1/integration/integrations", drop_fields=("credentials",)
    ),
    "lineage": SecodaEndpointConfig(name="lineage", path="/api/v1/lineage/manual/"),
}

ENDPOINTS = tuple(SECODA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
