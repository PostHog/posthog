from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

DOCS_URL = "https://io.catchpoint.com/api/swagger/v3.0/swagger.json"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tests": {
        "description": "Synthetic monitoring tests and their configuration.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique test identifier.",
            "name": "Test name.",
            "url": "URL that the test monitors.",
            "divisionId": "Identifier of the division that contains the test.",
            "productId": "Identifier of the product that contains the test.",
            "testType": "Type of synthetic test.",
            "monitor": "Monitor type used to run the test.",
            "status": "Test status.",
        },
    },
    "nodes": {
        "description": "Monitoring nodes across all network types.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique node identifier.",
            "name": "Node name.",
            "networkType": "Network type of the node.",
            "city": "City where the node runs.",
            "country": "Country where the node runs.",
            "status": "Node status.",
        },
    },
    "products": {
        "description": "Top-level containers that organize tests and define shared settings.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique product identifier.",
            "name": "Product name.",
            "divisionId": "Identifier of the division that contains the product.",
            "status": "Product status.",
        },
    },
    "folders": {
        "description": "Folders that organize tests within products.",
        "docs_url": DOCS_URL,
        "columns": {
            "id": "Unique folder identifier.",
            "name": "Folder name.",
            "productId": "Identifier of the product that contains the folder.",
            "divisionId": "Identifier of the division that contains the folder.",
        },
    },
    "divisions": {
        "description": "Account divisions accessible to the API consumer.",
        "docs_url": DOCS_URL,
        "columns": {"id": "Unique division identifier.", "name": "Division name."},
    },
}
