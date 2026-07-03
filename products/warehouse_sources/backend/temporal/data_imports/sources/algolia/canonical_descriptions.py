from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Algolia REST API reference (https://www.algolia.com/doc/rest-api/search/).
# `records` holds the user's own index objects, so its columns are index-specific and left to the
# LLM; only the universal `objectID` is documented here.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "records": {
        "description": "Every object stored in the Algolia index, retrieved via the browse endpoint.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Records/operation/browse",
        "columns": {
            "objectID": "Unique identifier of the record within the index.",
        },
    },
    "synonyms": {
        "description": "Synonyms configured on the index, defining terms Algolia treats as equivalent at query time.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Synonyms",
        "columns": {
            "objectID": "Unique identifier of the synonym.",
            "type": "Synonym type (e.g. synonym, oneWaySynonym, altCorrection1, placeholder).",
            "synonyms": "List of words considered equivalent.",
        },
    },
    "rules": {
        "description": "Query rules on the index that change ranking or results when a query matches their conditions.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Rules",
        "columns": {
            "objectID": "Unique identifier of the rule.",
            "conditions": "Conditions that trigger the rule.",
            "consequence": "Effect applied to the query when the rule's conditions match.",
            "enabled": "Whether the rule is currently active.",
        },
    },
    "indices": {
        "description": "All indices on the Algolia application with their size and timing metadata.",
        "docs_url": "https://www.algolia.com/doc/rest-api/search/#tag/Indices/operation/listIndices",
        "columns": {
            "name": "Index name.",
            "entries": "Number of records in the index.",
            "dataSize": "Size of the index data in bytes.",
            "fileSize": "Total size of the index including metadata, in bytes.",
            "createdAt": "Date the index was created (ISO 8601).",
            "updatedAt": "Date the index was last updated (ISO 8601).",
            "primary": "Name of the primary index, set on replica indices.",
        },
    },
}
