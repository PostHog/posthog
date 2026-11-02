from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from Groq's OpenAI-compatible API docs (https://console.groq.com/docs/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "batches": {
        "description": "Batch inference jobs submitted to the Batch API, with lifecycle status, request counts, and the file IDs holding the input, output, and errors.",
        "docs_url": "https://console.groq.com/docs/api-reference#batches",
        "columns": {
            "id": "Unique identifier for the batch job.",
            "object": "Object type, always `batch`.",
            "endpoint": "The API endpoint the batch runs against (e.g. /v1/chat/completions).",
            "input_file_id": "ID of the uploaded file containing the batch's input requests.",
            "completion_window": "Time frame within which the batch should be processed.",
            "status": "Current lifecycle status of the batch (e.g. validating, in_progress, completed, failed, expired).",
            "output_file_id": "ID of the file containing successful request outputs, once available.",
            "error_file_id": "ID of the file containing failed request errors, once available.",
            "created_at": "Unix timestamp (seconds) for when the batch was created.",
            "in_progress_at": "Unix timestamp (seconds) for when the batch started processing.",
            "expires_at": "Unix timestamp (seconds) for when the batch will expire.",
            "finalizing_at": "Unix timestamp (seconds) for when the batch started finalizing.",
            "completed_at": "Unix timestamp (seconds) for when the batch completed.",
            "failed_at": "Unix timestamp (seconds) for when the batch failed.",
            "expired_at": "Unix timestamp (seconds) for when the batch expired.",
            "cancelled_at": "Unix timestamp (seconds) for when the batch was cancelled.",
            "request_counts": "Object with total, completed, and failed request counts for the batch.",
            "metadata": "Set of key-value pairs attached to the batch at creation.",
        },
    },
    "files": {
        "description": "Metadata for files uploaded to Groq (typically batch inputs and outputs).",
        "docs_url": "https://console.groq.com/docs/api-reference#files",
        "columns": {
            "id": "Unique identifier for the file.",
            "object": "Object type, always `file`.",
            "bytes": "Size of the file in bytes.",
            "created_at": "Unix timestamp (seconds) for when the file was created.",
            "filename": "Name of the uploaded file.",
            "purpose": "Intended purpose of the file (e.g. batch, batch_output).",
        },
    },
    "models": {
        "description": "Catalog of models available to your organization through the Groq API.",
        "docs_url": "https://console.groq.com/docs/api-reference#models",
        "columns": {
            "id": "Model identifier used in API requests.",
            "object": "Object type, always `model`.",
            "created": "Unix timestamp (seconds) for when the model was created.",
            "owned_by": "Organization that owns the model.",
            "active": "Whether the model is currently active.",
            "context_window": "Maximum number of tokens the model can process in a single request.",
            "max_completion_tokens": "Maximum number of tokens the model can generate in a completion.",
        },
    },
}
