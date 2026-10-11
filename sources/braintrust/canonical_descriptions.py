from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects that organize experiments, datasets, prompts, and functions.",
        "docs_url": "https://www.braintrust.dev/docs/openapi.json",
        "columns": {
            "id": "The project's unique identifier.",
            "org_id": "The identifier of the organization that owns the project.",
            "name": "The project name.",
            "created": "The time when the project was created.",
            "deleted_at": "The time when the project was deleted, or null for an active project.",
        },
    },
    "experiments": {
        "description": "Evaluation experiments with their dataset, code revision, and comparison references.",
        "docs_url": "https://www.braintrust.dev/docs/openapi.json",
        "columns": {
            "id": "The experiment's unique identifier.",
            "project_id": "The identifier of the project that owns the experiment.",
            "name": "The experiment name, which is unique within its project.",
            "created": "The time when the experiment was created.",
            "commit": "The commit identifier from the repository information.",
            "dataset_id": "The linked dataset identifier, or null if no dataset is linked.",
            "dataset_version": "The dataset version used for the experiment.",
            "base_exp_id": "The default experiment used for comparison.",
        },
    },
    "datasets": {
        "description": "Dataset definitions used for evaluations. These rows do not contain dataset records.",
        "docs_url": "https://www.braintrust.dev/docs/openapi.json",
        "columns": {
            "id": "The dataset's unique identifier.",
            "project_id": "The identifier of the project that owns the dataset.",
            "name": "The dataset name, which is unique within its project.",
            "created": "The time when the dataset was created.",
            "metadata": "User-defined dataset metadata.",
        },
    },
    "prompts": {
        "description": "Saved prompts with their configuration and version identifiers.",
        "docs_url": "https://www.braintrust.dev/docs/openapi.json",
        "columns": {
            "id": "The prompt's unique identifier.",
            "project_id": "The identifier of the project that owns the prompt.",
            "name": "The prompt name.",
            "created": "The time when the prompt was created.",
            "_xact_id": "The transaction identifier used to retrieve a prompt version.",
        },
    },
    "functions": {
        "description": "Saved functions with their definitions, types, and parameter schemas.",
        "docs_url": "https://www.braintrust.dev/docs/openapi.json",
        "columns": {
            "id": "The function's unique identifier.",
            "project_id": "The identifier of the project that owns the function.",
            "name": "The function name.",
            "created": "The time when the function was created.",
            "function_schema": "The JSON schema for the function parameters and return value.",
        },
    },
}
