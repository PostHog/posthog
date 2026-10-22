"""Canonical, documentation-sourced descriptions for Cohere endpoints and columns.

Sourced from the official Cohere API reference (https://docs.cohere.com/reference). Keyed by the
endpoint names in `settings.py` `COHERE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced Cohere table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "datasets": {
        "description": "A dataset uploaded to Cohere for fine-tuning or embedding jobs.",
        "docs_url": "https://docs.cohere.com/reference/list-datasets",
        "columns": {
            "id": "Unique identifier for the dataset.",
            "name": "Human-readable name of the dataset.",
            "dataset_type": "The type of dataset (e.g. embed-input, chat-finetune-input).",
            "validation_status": "Whether the dataset passed validation (e.g. validated, failed).",
            "validation_error": "The validation error, if the dataset failed validation.",
            "created_at": "Time at which the dataset was created.",
            "updated_at": "Time at which the dataset was last updated.",
            "download_urls": "Signed URLs to download the dataset parts.",
            "schema": "The inferred schema of the dataset.",
        },
    },
    "models": {
        "description": "A model available to your account in the Cohere model catalog.",
        "docs_url": "https://docs.cohere.com/reference/list-models",
        "columns": {
            "name": "The model name, used as the identifier when calling the API.",
            "endpoints": "The API endpoints the model supports (e.g. generate, embed, chat, rerank).",
            "finetuned": "Whether the model is a fine-tuned model.",
            "context_length": "The maximum number of tokens the model accepts as input.",
            "tokenizer_url": "URL to the model's tokenizer configuration.",
            "default_endpoints": "The endpoints for which this model is the default.",
        },
    },
    "embed_jobs": {
        "description": "An asynchronous job that embeds a dataset into vectors.",
        "docs_url": "https://docs.cohere.com/reference/list-embed-jobs",
        "columns": {
            "job_id": "Unique identifier for the embed job.",
            "name": "Human-readable name of the embed job.",
            "status": "The status of the job (e.g. processing, complete, failed).",
            "created_at": "Time at which the embed job was created.",
            "input_dataset_id": "The dataset that was embedded.",
            "output_dataset_id": "The dataset holding the resulting embeddings.",
            "model": "The embedding model used for the job.",
            "truncate": "How inputs longer than the context length were truncated.",
            "meta": "Billed-unit metadata and API version info for the job.",
        },
    },
    "batches": {
        "description": "A batch job that runs an uploaded dataset of requests through a model.",
        "docs_url": "https://docs.cohere.com/reference/list-batches",
        "columns": {
            "id": "Unique identifier for the batch.",
            "name": "Human-readable name of the batch.",
            "creator_id": "ID of the user who created the batch.",
            "org_id": "ID of the organization that owns the batch.",
            "status": "Current stage in the life-cycle of the batch (e.g. BATCH_STATUS_IN_PROGRESS, BATCH_STATUS_COMPLETED).",
            "status_reason": "More details about the reason for the status of the batch.",
            "created_at": "Time at which the batch was created.",
            "updated_at": "Time at which the batch was last updated.",
            "input_dataset_id": "ID of the dataset the batch reads its requests from.",
            "output_dataset_id": "ID of the dataset the batch writes its outputs to.",
            "model": "The name of the model the batch uses.",
            "input_tokens": "The total number of input tokens in the batch.",
            "output_tokens": "The total number of output tokens in the batch.",
            "num_records": "The total number of records in the batch.",
            "num_successful_records": "The current number of successful records in the batch.",
            "num_failed_records": "The current number of failed records in the batch.",
        },
    },
}
