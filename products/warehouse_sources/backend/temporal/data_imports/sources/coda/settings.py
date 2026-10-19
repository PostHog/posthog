from dataclasses import dataclass, field


@dataclass
class CodaEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Coda's list endpoints have no updated-since filters (rows only sort), so
# every stream is a full refresh. Rows and columns fan out docs → tables → …;
# ids are only unique within their parent, hence the composite keys.
CODA_ENDPOINTS: dict[str, CodaEndpointConfig] = {
    "docs": CodaEndpointConfig(
        name="docs",
    ),
    "tables": CodaEndpointConfig(
        name="tables",
        primary_keys=["_doc_id", "id"],
    ),
    "rows": CodaEndpointConfig(
        name="rows",
        primary_keys=["_doc_id", "_table_id", "id"],
    ),
    "columns": CodaEndpointConfig(
        name="columns",
        primary_keys=["_doc_id", "_table_id", "id"],
    ),
    # Doc analytics returns one item per doc; the doc id is nested under `doc`, lifted to `doc_id`.
    "doc_analytics": CodaEndpointConfig(
        name="doc_analytics",
        primary_keys=["doc_id"],
    ),
    # Page analytics fans out over docs; the page id is nested under `page`, lifted to `page_id`.
    "page_analytics": CodaEndpointConfig(
        name="page_analytics",
        primary_keys=["_doc_id", "page_id"],
    ),
    "folders": CodaEndpointConfig(
        name="folders",
    ),
    "pages": CodaEndpointConfig(
        name="pages",
        primary_keys=["_doc_id", "id"],
    ),
    "permissions": CodaEndpointConfig(
        name="permissions",
        primary_keys=["_doc_id", "id"],
    ),
    # Workspace users carry no id; the email is unique within a workspace.
    "workspace_users": CodaEndpointConfig(
        name="workspace_users",
        primary_keys=["_workspace_id", "email"],
    ),
    # One row per workspace and month, with active and inactive user counts per role.
    "workspace_role_activity": CodaEndpointConfig(
        name="workspace_role_activity",
        primary_keys=["_workspace_id", "month"],
    ),
}

ENDPOINTS = tuple(CODA_ENDPOINTS.keys())

# Coda's list endpoints have no updated-since filters, so no stream is incremental.
INCREMENTAL_FIELDS: dict[str, list] = {}
