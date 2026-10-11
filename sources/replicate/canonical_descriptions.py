"""Canonical, documentation-sourced descriptions for Replicate endpoints and columns.

Sourced from the official Replicate HTTP API reference (https://replicate.com/docs/reference/http).
Keyed by the endpoint names in `settings.py` `REPLICATE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Replicate table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Predictions and trainings share the same run-record shape.
_RUN_COLUMNS = {
    "id": "Unique identifier for the run.",
    "model": "The model that was run, as owner/name.",
    "version": "The specific model version that was run.",
    "status": "Current status: starting, processing, succeeded, failed, or canceled.",
    "input": "The input payload the run was created with. Removed ~1 hour after completion for API-created runs.",
    "output": "The output the run produced. Removed ~1 hour after completion for API-created runs.",
    "error": "The error the run raised, if it failed.",
    "logs": "Execution logs. Removed ~1 hour after completion for API-created runs.",
    "source": "How the run was created: web or api.",
    "created_at": "Time at which the run was created.",
    "started_at": "Time at which the run started processing.",
    "completed_at": "Time at which the run finished (succeeded, failed, or canceled).",
    "metrics": "Runtime metrics such as predict_time.",
    "data_removed": "Whether the input/output/logs have been removed by Replicate's retention policy.",
    "urls": "API URLs to fetch, cancel, or view the run.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "predictions": {
        "description": "A prediction is a single run of a model on Replicate, with its input, output, status and timing.",
        "docs_url": "https://replicate.com/docs/reference/http#predictions.list",
        "columns": _RUN_COLUMNS,
    },
    "trainings": {
        "description": "A training is a fine-tuning run that produces a new model version from a base model.",
        "docs_url": "https://replicate.com/docs/reference/http#trainings.list",
        "columns": {
            **_RUN_COLUMNS,
            "output": "The training output, including the created model version and its weights.",
        },
    },
    "deployments": {
        "description": "A deployment is a private, managed endpoint for running a model with your own scaling configuration.",
        "docs_url": "https://replicate.com/docs/reference/http#deployments.list",
        "columns": {
            "owner": "The account that owns the deployment.",
            "name": "The deployment's name.",
            "current_release": "The currently deployed release, including its model, version and configuration.",
        },
    },
    "models": {
        "description": "A model on Replicate that can be run to make predictions. This table lists the public model catalog.",
        "docs_url": "https://replicate.com/docs/reference/http#models.list",
        "columns": {
            "url": "The web URL of the model.",
            "owner": "The account that owns the model.",
            "name": "The model's name.",
            "description": "A description of what the model does.",
            "visibility": "Whether the model is public or private.",
            "github_url": "The GitHub repository backing the model, if any.",
            "paper_url": "A link to a paper describing the model, if any.",
            "license_url": "A link to the model's license, if any.",
            "run_count": "The number of times the model has been run.",
            "cover_image_url": "A cover image for the model.",
            "default_example": "An example prediction for the model.",
            "latest_version": "The most recent version of the model.",
        },
    },
    "hardware": {
        "description": "A hardware SKU available for running models on Replicate.",
        "docs_url": "https://replicate.com/docs/reference/http#hardware.list",
        "columns": {
            "name": "Human-readable hardware name (e.g. Nvidia T4 GPU).",
            "sku": "The hardware SKU identifier (e.g. gpu-t4).",
        },
    },
    "account": {
        "description": "The authenticated Replicate account.",
        "docs_url": "https://replicate.com/docs/reference/http#accounts.get",
        "columns": {
            "type": "The account type: user or organization.",
            "username": "The account's username.",
            "name": "The account's display name.",
            "github_url": "The account's GitHub URL.",
        },
    },
}
