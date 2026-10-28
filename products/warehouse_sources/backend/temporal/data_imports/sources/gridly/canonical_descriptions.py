from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "records": {
        "description": "Content records of the configured Gridly view — one row per record, in the shape the Gridly API returns them.",
        "docs_url": "https://www.gridly.com/docs/api/",
        "columns": {
            "id": "Unique identifier of the record within the view.",
            "path": "Path to the folder where the record is stored.",
            "cells": "List of the record's cells, each with a `columnId` and `value` holding that column's data.",
        },
    },
    "columns": {
        "description": "Column definitions of the configured Gridly view, read from the view resource.",
        "docs_url": "https://www.gridly.com/docs/api/",
        "columns": {
            "id": "Unique identifier of the column.",
            "name": "Display name of the column.",
            "type": "Data type of the column (e.g. singleLine, number, language, reference).",
            "isSource": "Whether the column is a source (reference) column.",
            "isTarget": "Whether the column is a target (reference) column.",
            "languageCode": "Language code for localization columns.",
        },
    },
    "projects": {
        "description": "Projects in the Gridly company, the top level of the project > database > grid > view hierarchy.",
        "docs_url": "https://www.gridly.com/docs/api/#list-projects",
        "columns": {
            "id": "Unique identifier of the project.",
            "name": "Name of the project.",
            "description": "Description of the project.",
        },
    },
    "databases": {
        "description": "Databases in each Gridly project.",
        "docs_url": "https://www.gridly.com/docs/api/#list-databases",
        "columns": {
            "id": "Unique identifier of the database.",
            "name": "Name of the database.",
            "projectId": "ID of the project that owns the database.",
        },
    },
    "grids": {
        "description": "Grids (sheets or tables) in each Gridly database.",
        "docs_url": "https://www.gridly.com/docs/api/#list-grids",
        "columns": {
            "id": "Unique identifier of the grid.",
            "name": "Name of the grid.",
            "dbId": "ID of the database that owns the grid.",
        },
    },
    "views": {
        "description": "Views of each Gridly grid. A view displays all data of a grid or a subset of it, and is what the records and columns tables read from.",
        "docs_url": "https://www.gridly.com/docs/api/#list-views",
        "columns": {
            "id": "Unique identifier of the view.",
            "name": "Name of the view.",
            "gridId": "ID of the grid the view belongs to.",
        },
    },
    "branches": {
        "description": "Branches of each Gridly grid. A branch is a copy of a grid that you can change and then merge back.",
        "docs_url": "https://www.gridly.com/docs/api/#list-branches",
        "columns": {
            "id": "Unique identifier of the branch.",
            "name": "Name of the branch.",
            "gridId": "ID of the grid the branch belongs to.",
        },
    },
    "dependencies": {
        "description": "Column dependencies of the configured Gridly view. A dependency links a source column to a target column, so Gridly can track whether the target is up to date with the source.",
        "docs_url": "https://www.gridly.com/docs/api/#list-dependencies",
        "columns": {
            "id": "Unique identifier of the dependency.",
            "sourceColumnId": "ID of the source column.",
            "targetColumnId": "ID of the target column.",
        },
    },
    "automation_executions": {
        "description": "Run history of each automation of the configured Gridly view, one row per execution.",
        "docs_url": "https://www.gridly.com/docs/api/#list-executions-of-an-automation",
        "columns": {
            "id": "Identifier of the execution.",
            "status": "Status of the execution (e.g. STARTED, SUCCESS).",
            "startedTime": "Time the execution started.",
            "automationId": "ID of the automation that ran.",
        },
    },
    "record_histories": {
        "description": "Change history of each record of the configured Gridly view, one row per recorded change.",
        "docs_url": "https://www.gridly.com/docs/api/#get-record-history",
        "columns": {
            "lastModifiedBy": "User who made the change.",
            "lastModifiedTime": "Time of the change.",
            "path": "Path to the folder where the record was stored at the time of the change.",
            "cells": "List of the record's cells at the time of the change, each with a `columnId` and `value`, plus `dependencyStatus` and `sourceStatus` on localization columns.",
            "recordId": "ID of the record the history entry belongs to.",
        },
    },
}
