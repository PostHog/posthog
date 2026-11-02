"""Canonical, documentation-sourced descriptions for Smartsheet endpoints and columns.

Sourced from the official Smartsheet API reference (https://smartsheet.redoc.ly). Keyed by the
endpoint names in `settings.py` `SMARTSHEET_ENDPOINTS`, which match the `ExternalDataSchema.name`
of a synced Smartsheet table. Most are account-level list endpoints (sheet/report/workspace/
user/contact/template/group metadata); `sheet_rows` holds the cell data inside each sheet. Columns
absent here fall back to LLM enrichment.
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
    "report_columns": {
        "description": "A column in a report — one per report the account can access, fanned out across every report.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/reports/listreportcolumns",
        "columns": {
            "reportId": "Identifier of the report this column belongs to.",
            "virtualId": "The virtual ID of the report column, unique within its report.",
            "title": "The column's title.",
            "type": "The column type (e.g. TEXT_NUMBER, DATE, CONTACT_LIST, CHECKBOX).",
            "systemColumnType": "The system column type, if any (e.g. CREATED_BY, MODIFIED_DATE, AUTO_NUMBER).",
            "index": "Zero-based position of the column within the report.",
            "primary": "Whether this is the report's primary column.",
            "sheetNameColumn": "Whether this is the special sheet-name column identifying each row's source sheet.",
            "hidden": "Whether the column is hidden.",
            "width": "Display width of the column, in pixels.",
        },
    },
    "report_scope": {
        "description": "The scope of a report — its source sheets and source workspaces, fanned out across every report.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/reports/getreportscope",
        "columns": {
            "reportId": "Identifier of the report this scope entry belongs to.",
            "assetType": "The kind of source asset, either 'sheet' or 'workspace'.",
            "assetId": "Identifier of the source asset, according to its assetType.",
        },
    },
    "sheet_rows": {
        "description": "A row of a sheet, with its cells — fanned out across every sheet the account can access.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/sheets/getsheet",
        "columns": {
            "sheetId": "Identifier of the sheet this row belongs to.",
            "id": "Row ID.",
            "rowNumber": "Row number within the sheet.",
            "parentId": "Identifies the row that is the hierarchical parent of this row, if one exists.",
            "siblingId": "Identifies the row immediately above this row, if one exists.",
            "cells": "Cells belonging to the row. Each cell holds a columnId (see sheet_columns), a value and a displayValue.",
            "locked": "Whether the row is locked.",
            "createdAt": "Time at which the row was created.",
            "modifiedAt": "Time at which the row was last modified.",
        },
    },
    "sheet_columns": {
        "description": "A column of a sheet — fanned out across every sheet the account can access. Resolves the columnId of each cell in sheet_rows.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/columns/columns-listonsheet",
        "columns": {
            "sheetId": "Identifier of the sheet this column belongs to.",
            "id": "The column's unique identifier.",
            "index": "The column's position in the sheet. Indexes start at 0.",
            "title": "Column title.",
            "type": "The column type (e.g. TEXT_NUMBER, DATE, PICKLIST, CONTACT_LIST, CHECKBOX).",
            "primary": "Whether the column is the sheet's primary column.",
            "options": "The options of a picklist column.",
            "hidden": "Whether the column is hidden.",
            "locked": "Whether the column is locked.",
            "width": "The column's display width, in pixels.",
            "formula": "The formula for the column, if set.",
            "description": "Column description.",
        },
    },
    "events": {
        "description": "An event in the organization's activity stream — an action a user or system took on a Smartsheet object.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/events/list-events",
        "columns": {
            "eventId": "Unique event identifier.",
            "eventTimestamp": "Date and time of the event.",
            "objectType": "The Smartsheet resource that the event affected (e.g. SHEET, REPORT, USER).",
            "action": "The action applied to the object (e.g. CREATE, UPDATE, LOAD, DELETE).",
            "objectId": "Identifier of the object that the event affected.",
            "userId": "User assumed as the one who initiated the event.",
            "requestUserId": "User whose authentication credential is embedded in the request that initiated the event.",
            "accessTokenName": "Name of the access token embedded in the request, if any.",
            "source": "The client or user agent used to initiate the action.",
            "additionalDetails": "Properties specific to the event type.",
        },
    },
    "groups": {
        "description": "A group in the organization account.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/groups/list-groups",
        "columns": {
            "id": "Group ID.",
            "name": "Group name.",
            "description": "Group description.",
            "owner": "Group owner's email address.",
            "ownerId": "Group owner's user ID.",
            "createdAt": "Time at which the group was created.",
            "modifiedAt": "Time at which the group was last modified.",
        },
    },
    "group_members": {
        "description": "A member of a group — fanned out across every group in the organization account.",
        "docs_url": "https://developers.smartsheet.com/api/smartsheet/openapi/groups/get-group",
        "columns": {
            "groupId": "Identifier of the group this member belongs to.",
            "id": "Group member's user ID.",
            "email": "Group member's email address.",
            "name": "Group member's full name.",
            "firstName": "Group member's first name.",
            "lastName": "Group member's last name.",
        },
    },
}
