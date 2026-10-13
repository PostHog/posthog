"""Canonical, documentation-sourced descriptions for Coda endpoints and columns.

Sourced from the official Coda API reference (https://coda.io/developers/apis/v1). Keyed by the
endpoint names in `settings.py` `CODA_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Coda table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "docs": {
        "description": "A Coda doc — the top-level document containing tables, pages, and content.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Docs",
        "columns": {
            "id": "Unique identifier for the doc.",
            "name": "The doc's name.",
            "type": "Type of the object, always 'doc'.",
            "href": "API URL of the doc.",
            "browserLink": "URL to open the doc in a browser.",
            "owner": "Email address of the doc's owner.",
            "ownerName": "Name of the doc's owner.",
            "createdAt": "Time at which the doc was created.",
            "updatedAt": "Time at which the doc was last updated.",
            "workspaceId": "ID of the workspace the doc belongs to.",
            "folderId": "ID of the folder the doc belongs to.",
        },
    },
    "tables": {
        "description": "A table within a Coda doc, holding a set of columns and rows.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Tables",
        "columns": {
            "id": "Identifier for the table, unique within its doc.",
            "name": "The table's name.",
            "type": "Type of the object, always 'table'.",
            "href": "API URL of the table.",
            "browserLink": "URL to open the table in a browser.",
            "tableType": "Whether the object is a table or a view.",
            "rowCount": "Number of rows in the table.",
            "displayColumn": "The table's display column.",
            "createdAt": "Time at which the table was created.",
            "updatedAt": "Time at which the table was last updated.",
            "_doc_id": "Identifier of the parent doc, injected during the fan-out sync.",
        },
    },
    "rows": {
        "description": "A row in a Coda table, with its cell values keyed by column.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Rows",
        "columns": {
            "id": "Identifier for the row, unique within its table.",
            "name": "The row's display name (value of the display column).",
            "type": "Type of the object, always 'row'.",
            "href": "API URL of the row.",
            "browserLink": "URL to open the row in a browser.",
            "index": "Position (index) of the row within the table.",
            "values": "Map of column identifiers to the row's cell values.",
            "createdAt": "Time at which the row was created.",
            "updatedAt": "Time at which the row was last updated.",
            "_doc_id": "Identifier of the parent doc, injected during the fan-out sync.",
            "_table_id": "Identifier of the parent table, injected during the fan-out sync.",
        },
    },
    "columns": {
        "description": "A column definition within a Coda table, giving the name, type, and formula for the column ids used as keys in each row's values.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Columns",
        "columns": {
            "id": "Identifier for the column, unique within its table.",
            "name": "The column's name.",
            "type": "Type of the object, always 'column'.",
            "href": "API URL of the column.",
            "display": "Whether the column is the table's display column.",
            "calculated": "Whether the column is a formula column.",
            "formula": "The column's formula, if it is calculated.",
            "defaultValue": "The column's default value, if any.",
            "format": "The column's format (its value type and format options).",
            "_doc_id": "Identifier of the parent doc, injected during the fan-out sync.",
            "_table_id": "Identifier of the parent table, injected during the fan-out sync.",
        },
    },
    "doc_analytics": {
        "description": "Per-doc usage analytics for the workspace: one item per doc, with a metrics list of views, sessions, and AI credit usage over time.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Analytics",
        "columns": {
            "doc_id": "Identifier of the doc these analytics describe, lifted from the nested doc object.",
            "doc": "Metadata about the doc (id, title, creation and publish time).",
            "metrics": "List of per-period metrics (views, copies, likes, sessions by device, and AI credits) with the date of each period.",
        },
    },
    "page_analytics": {
        "description": "Page-level view analytics within a doc: one item per page, with a metrics list of views, sessions, and time-viewed over time.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Analytics",
        "columns": {
            "page_id": "Identifier of the page these analytics describe, lifted from the nested page object.",
            "page": "Metadata about the page (id and name).",
            "metrics": "List of per-period metrics (views, sessions, unique users, and time viewed) with the date of each period.",
            "_doc_id": "Identifier of the parent doc, injected during the fan-out sync.",
        },
    },
    "folders": {
        "description": "A folder in a workspace, resolving the folder reference each doc carries.",
        "docs_url": "https://coda.io/developers/apis/v1#tag/Folders",
        "columns": {
            "id": "Unique identifier for the folder.",
            "name": "The folder's name.",
            "type": "Type of the object, always 'folder'.",
            "browserLink": "URL to open the folder in a browser.",
            "description": "The folder's description.",
            "icon": "The folder's icon.",
            "iconColor": "The folder's icon color.",
            "createdAt": "Time at which the folder was created.",
            "canEdit": "Whether the API token's owner can edit the folder.",
            "workspace": "Reference to the workspace the folder belongs to.",
        },
    },
}
