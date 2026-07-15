from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from Nebius AI Studio (Token Factory) docs, which follow the OpenAI-compatible
# object schemas. Keyed by the endpoint/schema name returned by `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "models": {
        "description": "Models available to your Nebius AI Studio account for inference and fine-tuning.",
        "docs_url": "https://docs.tokenfactory.nebius.com/api-reference",
        "columns": {
            "id": "Model identifier used when requesting inference (e.g. meta-llama/Llama-3.3-70B-Instruct).",
            "object": "Object type, always 'model'.",
            "created": "Unix timestamp (seconds) for when the model was created.",
            "owned_by": "Organization or provider that owns the model.",
        },
    },
    "files": {
        "description": "Files uploaded to Nebius AI Studio, such as batch inputs and fine-tuning datasets.",
        "docs_url": "https://docs.tokenfactory.nebius.com/api-reference",
        "columns": {
            "id": "Unique identifier for the file.",
            "object": "Object type, always 'file'.",
            "bytes": "Size of the file in bytes.",
            "created_at": "Unix timestamp (seconds) for when the file was created.",
            "filename": "Name of the uploaded file.",
            "purpose": "Intended use of the file (e.g. 'batch', 'fine-tune').",
            "status": "Processing status of the file.",
        },
    },
    "batches": {
        "description": "Batch inference jobs that process a file of requests asynchronously.",
        "docs_url": "https://docs.tokenfactory.nebius.com/api-reference",
        "columns": {
            "id": "Unique identifier for the batch.",
            "object": "Object type, always 'batch'.",
            "endpoint": "API endpoint the batch runs against (e.g. /v1/chat/completions).",
            "input_file_id": "ID of the uploaded file containing the batch's requests.",
            "completion_window": "Time window within which the batch should be processed.",
            "status": "Current status of the batch (e.g. validating, in_progress, completed, failed).",
            "output_file_id": "ID of the file containing successful request outputs.",
            "error_file_id": "ID of the file containing failed request errors.",
            "created_at": "Unix timestamp (seconds) for when the batch was created.",
            "completed_at": "Unix timestamp (seconds) for when the batch finished.",
            "request_counts": "Counts of total, completed, and failed requests in the batch.",
        },
    },
    "fine_tuning_jobs": {
        "description": "Fine-tuning jobs that train a custom model from a base model and a training file.",
        "docs_url": "https://docs.tokenfactory.nebius.com/api-reference",
        "columns": {
            "id": "Unique identifier for the fine-tuning job.",
            "object": "Object type, always 'fine_tuning.job'.",
            "model": "Base model being fine-tuned.",
            "created_at": "Unix timestamp (seconds) for when the job was created.",
            "finished_at": "Unix timestamp (seconds) for when the job finished, if it has.",
            "fine_tuned_model": "Identifier of the resulting fine-tuned model, once available.",
            "status": "Current status of the job (e.g. queued, running, succeeded, failed, cancelled).",
            "training_file": "ID of the file used for training.",
            "validation_file": "ID of the file used for validation, if provided.",
            "hyperparameters": "Hyperparameters used for the fine-tuning run.",
            "trained_tokens": "Total number of billable tokens processed by the job.",
        },
    },
}
