from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the Fireworks AI control-plane API reference
# (https://docs.fireworks.ai/api-reference). Keyed by the endpoint/schema name from settings.py.
# Partial coverage is fine — anything omitted falls back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "models": {
        "description": "Models available in the account, including base models, fine-tuned outputs, and imported models.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-models",
        "columns": {
            "name": "Resource name of the model (e.g. accounts/{account_id}/models/{model_id}).",
            "displayName": "Human-readable name of the model.",
            "description": "Description of the model.",
            "createTime": "Time the model was created.",
            "updateTime": "Time the model was last updated.",
            "state": "Lifecycle state of the model.",
            "status": "Detailed status of the model.",
            "kind": "Kind of model (e.g. base model, fine-tuned model).",
            "public": "Whether the model is publicly available.",
            "contextLength": "Maximum context length supported by the model.",
            "supportsImageInput": "Whether the model accepts image input.",
            "supportsTools": "Whether the model supports tool/function calling.",
            "baseModelDetails": "Details of the base model this model derives from.",
            "fineTuningJob": "Name of the fine-tuning job that produced this model, if any.",
        },
    },
    "deployments": {
        "description": "Dedicated on-demand deployments serving models on Fireworks GPUs.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-deployments",
        "columns": {
            "name": "Resource name of the deployment (e.g. accounts/{account_id}/deployments/{deployment_id}).",
            "displayName": "Human-readable name of the deployment.",
            "createTime": "Time the deployment was created.",
            "state": "Lifecycle state of the deployment.",
        },
    },
    "datasets": {
        "description": "Datasets uploaded for fine-tuning and evaluation, stored as JSONL training examples.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-datasets",
        "columns": {
            "name": "Resource name of the dataset (e.g. accounts/{account_id}/datasets/{dataset_id}).",
            "displayName": "Human-readable name of the dataset.",
            "createTime": "Time the dataset was created.",
            "updateTime": "Time the dataset was last updated.",
            "state": "Upload state of the dataset (UPLOADING, READY, ...).",
            "exampleCount": "Number of training examples in the dataset.",
            "format": "Format of the dataset.",
            "userUploaded": "Whether the dataset was uploaded by the user.",
            "createdBy": "Identity that created the dataset.",
        },
    },
    "supervised_fine_tuning_jobs": {
        "description": "Supervised fine-tuning (SFT) jobs that train a model on a labeled dataset.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-supervised-fine-tuning-jobs",
        "columns": {
            "name": "Resource name of the fine-tuning job.",
            "displayName": "Human-readable name of the job.",
            "createTime": "Time the job was created.",
            "updateTime": "Time the job was last updated.",
            "completedTime": "Time the job completed.",
            "state": "Lifecycle state of the job (CREATING, RUNNING, COMPLETED, FAILED, ...).",
            "status": "Detailed status of the job.",
            "dataset": "Dataset used to train the model.",
            "baseModel": "Base model the job fine-tunes.",
            "outputModel": "Model produced by the job.",
            "createdBy": "Identity that created the job.",
        },
    },
    "reinforcement_fine_tuning_jobs": {
        "description": "Reinforcement fine-tuning (RFT) jobs that train a model with a reward signal.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-reinforcement-fine-tuning-jobs",
        "columns": {
            "name": "Resource name of the reinforcement fine-tuning job.",
            "createTime": "Time the job was created.",
            "completedTime": "Time the job completed.",
            "state": "Lifecycle state of the job.",
        },
    },
    "evaluation_jobs": {
        "description": "Evaluation jobs that score a model against an evaluator and dataset.",
        "docs_url": "https://docs.fireworks.ai/api-reference/list-evaluation-jobs",
        "columns": {
            "name": "Resource name of the evaluation job.",
            "createTime": "Time the job was created.",
            "updateTime": "Time the job was last updated.",
            "state": "Lifecycle state of the job.",
        },
    },
}
