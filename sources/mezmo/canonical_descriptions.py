from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pipelines": {
        "description": "Telemetry pipelines in the Mezmo account.",
        "docs_url": "https://docs.mezmo.com/apis/combined-mezmo-api.yaml",
        "columns": {
            "id": "Unique pipeline identifier.",
            "title": "Pipeline title.",
        },
    },
    "alerts": {
        "description": "Alert configurations attached to pipeline components.",
        "docs_url": "https://docs.mezmo.com/apis/combined-mezmo-api.yaml",
        "columns": {
            "id": "Unique alert identifier.",
            "pipeline_id": "Identifier of the pipeline that contains the alert.",
            "component_id": "Identifier of the component that the alert monitors.",
            "component_kind": "Kind of component that the alert monitors.",
            "active": "Whether the alert is enabled.",
        },
    },
    "pipeline_health": {
        "description": "Current source health for active, published pipelines over the default 15-minute interval.",
        "docs_url": "https://docs.mezmo.com/apis/combined-mezmo-api.yaml",
        "columns": {
            "id": "Unique pipeline identifier.",
            "title": "Pipeline title.",
            "published_at": "Time when the pipeline was last published.",
            "sources": "Source components and their processing lag. Lag is a relative measure, not an exact event count.",
        },
    },
}
