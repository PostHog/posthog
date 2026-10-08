from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "models": {
        "description": "Models in the selected Clarifai app, including details of their latest versions.",
        "docs_url": "https://docs.clarifai.com/create/models/manage/",
        "columns": {
            "id": "Model identifier within the app.",
            "name": "Model name.",
            "app_id": "Identifier of the app that contains the model.",
            "user_id": "Identifier of the model owner.",
            "model_version": "Details of the latest model version.",
        },
    },
    "workflows": {
        "description": "Workflows that connect models in the selected Clarifai app.",
        "docs_url": "https://docs.clarifai.com/create/workflows/manage/",
        "columns": {
            "id": "Workflow identifier within the app.",
            "nodes": "Model nodes and their connections in the workflow.",
        },
    },
    "datasets": {
        "description": "Datasets that organize inputs in the selected Clarifai app.",
        "docs_url": "https://docs.clarifai.com/create/datasets/manage/",
        "columns": {
            "id": "Dataset identifier within the app.",
            "description": "Description of the dataset.",
            "metadata": "Custom metadata attached to the dataset.",
        },
    },
    "concepts": {
        "description": "Concept labels in the selected Clarifai app.",
        "docs_url": "https://docs.clarifai.com/create/concepts/manage/",
        "columns": {
            "id": "Concept identifier within the app.",
            "name": "Concept name.",
            "language": "Language of the concept name.",
            "created_at": "Time when the concept was created.",
            "app_id": "Identifier of the app that contains the concept.",
        },
    },
}
