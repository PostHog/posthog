from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Metabase API reference (https://www.metabase.com/docs/latest/api-documentation).
# Partial coverage is fine — any endpoint, column, or table-level description not listed here falls
# back to the LLM enrichment pass.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "cards": {
        "description": 'Saved questions ("cards") — individual queries or visualizations saved in Metabase.',
        "docs_url": "https://www.metabase.com/docs/latest/api/card",
        "columns": {
            "id": "Unique identifier for the card.",
            "name": "Display name of the saved question.",
            "description": "Optional human description of the card.",
            "collection_id": "Id of the collection the card lives in (null for the root collection).",
            "database_id": "Id of the database the card queries.",
            "table_id": "Id of the primary table the card queries, when applicable.",
            "query_type": 'Whether the card uses the query builder ("query") or native SQL ("native").',
            "display": "Visualization type (e.g. table, line, bar, scalar).",
            "creator_id": "Id of the user who created the card.",
            "archived": "Whether the card has been archived.",
            "created_at": "Timestamp when the card was created.",
            "updated_at": "Timestamp when the card was last updated.",
        },
    },
    "dashboards": {
        "description": "Dashboards — collections of cards arranged on a grid.",
        "docs_url": "https://www.metabase.com/docs/latest/api/dashboard",
        "columns": {
            "id": "Unique identifier for the dashboard.",
            "name": "Display name of the dashboard.",
            "description": "Optional human description of the dashboard.",
            "collection_id": "Id of the collection the dashboard lives in (null for the root collection).",
            "creator_id": "Id of the user who created the dashboard.",
            "archived": "Whether the dashboard has been archived.",
            "created_at": "Timestamp when the dashboard was created.",
            "updated_at": "Timestamp when the dashboard was last updated.",
        },
    },
    "collections": {
        "description": "Collections — folders that organize cards, dashboards, and other collections.",
        "docs_url": "https://www.metabase.com/docs/latest/api/collection",
        "columns": {
            "id": 'Unique identifier for the collection (may be the string "root").',
            "name": "Display name of the collection.",
            "description": "Optional human description of the collection.",
            "slug": "URL-friendly slug derived from the name.",
            "color": "Hex color used for the collection's icon.",
            "location": "Materialized path of ancestor collection ids.",
            "personal_owner_id": "User id when this is a user's personal collection, else null.",
            "archived": "Whether the collection has been archived.",
        },
    },
    "databases": {
        "description": "Databases connected to the Metabase instance that cards and dashboards query against.",
        "docs_url": "https://www.metabase.com/docs/latest/api/database",
        "columns": {
            "id": "Unique identifier for the database connection.",
            "name": "Display name of the database connection.",
            "engine": "Database engine (e.g. postgres, mysql, bigquery).",
            "is_sample": "Whether this is Metabase's bundled sample database.",
            "is_on_demand": "Whether field values are cached on demand rather than on a schedule.",
            "created_at": "Timestamp when the database connection was created.",
            "updated_at": "Timestamp when the database connection was last updated.",
        },
    },
    "users": {
        "description": "Metabase user accounts.",
        "docs_url": "https://www.metabase.com/docs/latest/api/user",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "User's email address (login).",
            "first_name": "User's first name.",
            "last_name": "User's last name.",
            "common_name": "Full display name.",
            "is_superuser": "Whether the user is an administrator.",
            "is_active": "Whether the account is active (not deactivated).",
            "is_qbnewb": "Whether the user has not yet dismissed the query-builder onboarding.",
            "last_login": "Timestamp of the user's most recent login.",
            "date_joined": "Timestamp when the account was created.",
        },
    },
    "native_query_snippets": {
        "description": "Reusable native (SQL) query snippets that can be inserted into native questions.",
        "docs_url": "https://www.metabase.com/docs/latest/api/native-query-snippet",
        "columns": {
            "id": "Unique identifier for the snippet.",
            "name": "Display name of the snippet.",
            "description": "Optional human description of the snippet.",
            "content": "The SQL fragment the snippet expands to.",
            "collection_id": "Id of the snippet collection it belongs to, if any.",
            "creator_id": "Id of the user who created the snippet.",
            "archived": "Whether the snippet has been archived.",
            "created_at": "Timestamp when the snippet was created.",
            "updated_at": "Timestamp when the snippet was last updated.",
        },
    },
}
