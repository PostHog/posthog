from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "records": {
        "description": "Every key/value pair in the Storage by Zapier store, one row per key.",
        "docs_url": "https://help.zapier.com/hc/en-us/articles/8496293271053",
        "columns": {
            "key": "The store key (max 32 characters). Unique within the store.",
            "value": "The value stored under the key, returned as a string (JSON-encoded when not already a string).",
        },
    },
}
