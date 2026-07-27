"""Canonical, documentation-sourced descriptions for Smartsheet endpoints and columns.

Sourced from the official Smartsheet API reference (https://smartsheet.redoc.ly). Keyed by the
endpoint names in `settings.py` `SMARTSHEET_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Smartsheet table. These are the account-level list endpoints (sheet/report/workspace/
user/contact/template metadata) — not the user-defined cell data inside a sheet. Columns absent
here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sheets": {
        "description": "Metadata for a sheet the account can access (the grid where rows and columns of data live).",
        "docs_url": "https://smartsheet.redoc.ly/tag/sheets#operation/list-sheets",
        "columns": {
            "id": "Unique identifier for the sheet.",
            "name": "The sheet's name.",
            "accessLevel": "The account's access level on the sheet (e.g. OWNER, ADMIN, EDITOR, VIEWER).",
            "permalink": "URL that opens the sheet in the Smartsheet app.",
            "createdAt": "Time at which the sheet was created.",
            "modifiedAt": "Time at which the sheet was last modified.",
        },
    },
    "reports": {
        "description": "Metadata for a report — a filtered, cross-sheet view of rows the account can access.",
        "docs_url": "https://smartsheet.redoc.ly/tag/reports#operation/list-reports",
        "columns": {
            "id": "Unique identifier for the report.",
            "name": "The report's name.",
            "accessLevel": "The account's access level on the report (e.g. OWNER, ADMIN, EDITOR, VIEWER).",
            "permalink": "URL that opens the report in the Smartsheet app.",
            "createdAt": "Time at which the report was created.",
            "modifiedAt": "Time at which the report was last modified.",
        },
    },
    "workspaces": {
        "description": "Metadata for a workspace — a container that groups sheets, reports, and dashboards.",
        "docs_url": "https://smartsheet.redoc.ly/tag/workspaces#operation/list-workspaces",
        "columns": {
            "id": "Unique identifier for the workspace.",
            "name": "The workspace's name.",
            "accessLevel": "The account's access level on the workspace (e.g. OWNER, ADMIN, EDITOR, VIEWER).",
            "permalink": "URL that opens the workspace in the Smartsheet app.",
        },
    },
    "users": {
        "description": "A user in the Smartsheet organization (requires a system administrator account).",
        "docs_url": "https://smartsheet.redoc.ly/tag/users#operation/list-users",
        "columns": {
            "id": "Unique identifier for the user.",
            "email": "The user's email address.",
            "firstName": "The user's first name.",
            "lastName": "The user's last name.",
            "name": "The user's full name.",
            "admin": "Whether the user is a system administrator.",
            "licensedSheetCreator": "Whether the user holds a license to create sheets.",
            "status": "The user's account status (e.g. ACTIVE, PENDING, DECLINED).",
        },
    },
    "contacts": {
        "description": "A contact in the account's personal contact list, usable when assigning rows.",
        "docs_url": "https://smartsheet.redoc.ly/tag/contacts#operation/list-contacts",
        "columns": {
            "id": "Unique identifier for the contact.",
            "name": "The contact's name.",
            "email": "The contact's email address.",
        },
    },
    "templates": {
        "description": "Metadata for a template the account can use to create new sheets.",
        "docs_url": "https://smartsheet.redoc.ly/tag/templates#operation/list-user-created-templates",
        "columns": {
            "id": "Unique identifier for the template.",
            "name": "The template's name.",
            "description": "Description of the template.",
            "accessLevel": "The account's access level on the template.",
            "type": "The type of object the template creates (e.g. sheet).",
        },
    },
}
