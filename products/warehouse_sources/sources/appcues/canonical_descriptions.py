from products.warehouse_sources.backend.temporal.data_imports.sources.appcues.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    name: {
        "description": endpoint.description,
        "docs_url": f"https://api.appcues.com/v2/docs#{endpoint.docs_anchor}",
        "columns": {
            "id": "Unique identifier for this record within the Appcues account.",
            "created_at": "Time when the record was created.",
            "updated_at": "Time when the record was last changed.",
            "created_by": "Identifier of the user who created the record.",
            "updated_by": "Identifier of the user who last changed the record.",
        },
    }
    for name, endpoint in ENDPOINTS.items()
}
