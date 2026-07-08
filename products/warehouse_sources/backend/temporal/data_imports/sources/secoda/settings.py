from dataclasses import dataclass, field


@dataclass
class SecodaEndpointConfig:
    name: str
    path: str
    # Secoda resource identifiers are workspace-unique UUIDs, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


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
}

ENDPOINTS = tuple(SECODA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
