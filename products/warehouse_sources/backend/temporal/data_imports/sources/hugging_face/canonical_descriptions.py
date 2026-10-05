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
    "discussions": {
        "description": "A discussion or pull request on a model, dataset, or Space repository owned by the connected namespace.",
        "docs_url": "https://huggingface.co/docs/hub/repositories-pull-requests-discussions",
        "columns": {
            "num": "Number of the discussion, unique within its repository.",
            "repo_type": "Kind of repository the discussion belongs to (model, dataset, or space).",
            "repo_name": "Repository identifier in `namespace/name` form.",
            "repo": "The repository the discussion belongs to.",
            "title": "Title of the discussion.",
            "status": "Status of the discussion (open, closed, merged, or draft).",
            "isPullRequest": "Whether the discussion is a pull request.",
            "author": "The user or organization that opened the discussion.",
            "createdAt": "Time at which the discussion was opened.",
            "numComments": "Number of comments on the discussion.",
            "numReactionUsers": "Number of users who reacted to the discussion.",
            "topReactions": "The most used reactions on the discussion.",
            "pinned": "Whether the discussion is pinned on the repository.",
            "repoOwner": "The owner of the repository and its relation to the discussion.",
        },
    },
    "collections": {
        "description": "A collection owned by the connected namespace, grouping models, datasets, Spaces, and papers.",
        "docs_url": "https://huggingface.co/docs/hub/collections",
        "columns": {
            "slug": "Collection identifier in `namespace/title-id` form (unique across the Hub).",
            "title": "Title of the collection.",
            "description": "Description of the collection.",
            "owner": "The user or organization that owns the collection.",
            "items": "The models, datasets, Spaces, and papers in the collection.",
            "lastUpdated": "Time at which the collection was last updated.",
            "private": "Whether the collection is private.",
            "upvotes": "Number of upvotes on the collection.",
            "theme": "Display color theme of the collection.",
            "gating": "Access-gating status applied to the collection's items.",
        },
    },
    "likes": {
        "description": "A repository liked by the connected user. Empty when the namespace is an organization.",
        "docs_url": "https://huggingface.co/docs/hub/api",
        "columns": {
            "repo_type": "Kind of liked repository (model, dataset, or space).",
            "repo_name": "Liked repository identifier in `namespace/name` form.",
            "repo": "The liked repository.",
            "createdAt": "Time at which the user liked the repository.",
        },
    },
    "model_tags": {
        "description": "Lookup of the tags that can appear on model repositories, grouped by tag type.",
        "docs_url": "https://huggingface.co/docs/hub/api",
        "columns": {
            "id": "Tag string as it appears in a model's `tags`.",
            "label": "Human-readable label of the tag.",
            "type": "Tag type (e.g. pipeline_tag, library, language, license).",
            "subType": "Optional subdivision of the tag type.",
        },
    },
    "dataset_tags": {
        "description": "Lookup of the tags that can appear on dataset repositories, grouped by tag type.",
        "docs_url": "https://huggingface.co/docs/hub/api",
        "columns": {
            "id": "Tag string as it appears in a dataset's `tags`.",
            "label": "Human-readable label of the tag.",
            "type": "Tag type (e.g. task_categories, modality, format, license).",
            "subType": "Optional subdivision of the tag type.",
        },
    },
}
