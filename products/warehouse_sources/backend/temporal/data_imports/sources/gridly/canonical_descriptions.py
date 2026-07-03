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
}
