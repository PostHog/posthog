from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalEndpoint,
)

NODE_DESCRIPTION: CanonicalEndpoint = {
    "description": "Nodes with this label, including their properties and labels.",
    "docs_url": "https://neo4j.com/docs/query-api/current/plain-json/",
    "columns": {
        "element_id": "The node identifier. Neo4j does not guarantee its identity across transactions.",
        "labels": "The labels attached to the node.",
    },
}

RELATIONSHIP_DESCRIPTION: CanonicalEndpoint = {
    "description": "Relationships of this type, including their properties and connected node identifiers.",
    "docs_url": "https://neo4j.com/docs/query-api/current/plain-json/",
    "columns": {
        "element_id": "The relationship identifier. Neo4j does not guarantee its identity across transactions.",
        "start_element_id": "The identifier of the start node.",
        "end_element_id": "The identifier of the end node.",
    },
}
