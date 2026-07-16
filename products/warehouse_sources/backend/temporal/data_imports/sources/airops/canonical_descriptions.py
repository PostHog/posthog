from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the AirOps public API reference (https://docs.airops.com/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "apps": {
        "description": "An AirOps app (workflow or agent) in your workspace.",
        "docs_url": "https://docs.airops.com/api-reference/api-reference/apps",
        "columns": {
            "id": "Unique identifier for the app.",
            "uuid": "Globally unique 36-character identifier for the app.",
            "name": "Human-readable name of the app.",
            "description": "Description of what the app does.",
            "readme": "Long-form README/documentation for the app.",
            "emoji": "Emoji shown as the app's icon.",
            "background_color": "Background color used for the app's icon.",
            "public": "Whether the app is publicly accessible.",
            "active_version_id": "Identifier of the app version currently published as active.",
            "created_at": "Timestamp when the app was created.",
            "updated_at": "Timestamp when the app was last updated.",
        },
    },
    "executions": {
        "description": "A single run of an AirOps app, including its inputs, output, and run metadata.",
        "docs_url": "https://docs.airops.com/api-reference/api-reference/executions",
        "columns": {
            "id": "Unique identifier for the execution.",
            "uuid": "Globally unique 36-character identifier for the execution.",
            "airops_app_id": "Identifier of the parent app this execution belongs to.",
            "airops_apps_version_id": "Identifier of the app version that produced this execution.",
            "workspace_id": "Identifier of the workspace the execution ran in.",
            "conversation_id": "Identifier of the conversation this execution is part of, when applicable.",
            "status": "Execution status: pending, running, error, success, cancelled, or review_needed.",
            "inputs": "Free-form JSON object of the inputs the app was run with.",
            "output": "Free-form JSON object of the app's output.",
            "credits_used": "Number of AirOps credits consumed by the execution.",
            "runtime": "Time it took to execute the app, in seconds.",
            "source": "Where the execution was triggered from.",
            "feedback": "User feedback on the execution: positive, neutral, or negative.",
            "error_code": "Error code when the execution failed.",
            "error_message": "Error message when the execution failed.",
            "createdAt": "Timestamp when the execution was created.",
            "updatedAt": "Timestamp when the execution was last updated.",
        },
    },
}
