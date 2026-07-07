"""Canonical, documentation-sourced descriptions for Hugging Face Hub endpoints and columns.

Sourced from the official Hugging Face Hub API reference (https://huggingface.co/docs/hub/api).
Keyed by the endpoint names in `settings.py` `HUGGING_FACE_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced Hugging Face table. Columns absent here fall back to LLM
enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Fields common to every repo kind returned by the list endpoints.
_COMMON_COLUMNS = {
    "id": "Repository identifier in `namespace/name` form (unique across the Hub).",
    "_id": "Internal database identifier for the repository.",
    "author": "The user or organization that owns the repository.",
    "private": "Whether the repository is private.",
    "gated": "Access-gating status of the repository (false, or a gating mode such as 'auto' or 'manual').",
    "likes": "Number of users who have liked the repository.",
    "tags": "Tags attached to the repository (task, library, language, license, etc.).",
    "createdAt": "Time at which the repository was created.",
    "lastModified": "Time at which the repository was last modified.",
    "sha": "Commit SHA of the current main revision.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "models": {
        "description": "A model repository on the Hugging Face Hub, owned by the connected namespace.",
        "docs_url": "https://huggingface.co/docs/hub/api#get-apimodels",
        "columns": {
            **_COMMON_COLUMNS,
            "modelId": "Alias of `id`; the model repository identifier.",
            "downloads": "Number of downloads of the model in the last 30 days.",
            "pipeline_tag": "The primary task the model is for (e.g. text-generation, image-classification).",
            "library_name": "The library the model is compatible with (e.g. transformers, diffusers).",
            "trendingScore": "Score used to rank trending models.",
            "siblings": "The files that make up the model repository.",
        },
    },
    "datasets": {
        "description": "A dataset repository on the Hugging Face Hub, owned by the connected namespace.",
        "docs_url": "https://huggingface.co/docs/hub/api#get-apidatasets",
        "columns": {
            **_COMMON_COLUMNS,
            "downloads": "Number of downloads of the dataset in the last 30 days.",
            "disabled": "Whether the dataset has been disabled.",
            "key": "Internal search/relevance key for the dataset.",
        },
    },
    "spaces": {
        "description": "A Space (hosted app) repository on the Hugging Face Hub, owned by the connected namespace.",
        "docs_url": "https://huggingface.co/docs/hub/api#get-apispaces",
        "columns": {
            **_COMMON_COLUMNS,
            "sdk": "The SDK the Space runs on (e.g. gradio, streamlit, docker, static).",
        },
    },
}
