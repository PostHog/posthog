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
}
