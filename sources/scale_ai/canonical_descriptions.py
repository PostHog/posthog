from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "tasks": {
        "description": "A unit of data labeling work submitted to Scale, with its type, status, timestamps, and review results.",
        "docs_url": "https://scale.com/docs/api-reference/tasks",
        "columns": {
            "task_id": "Unique identifier for the task.",
            "type": "The task type (e.g. imageannotation, categorization, textcollection).",
            "status": "Current lifecycle status of the task (pending, completed, or canceled).",
            "project": "Name of the project the task belongs to.",
            "batch": "Name of the batch the task belongs to, if any.",
            "created_at": "When the task was created.",
            "completed_at": "When the task was completed, if it has been.",
            "updated_at": "When the task was last updated.",
            "callback_url": "URL Scale calls when the task completes.",
            "instruction": "Instructions shown to the labeler for this task.",
            "params": "Task-type-specific parameters supplied at creation.",
            "response": "The completed labeling response, present once the task is done.",
            "metadata": "Arbitrary customer-supplied metadata attached to the task.",
            "customer_review_status": "Audit result for the task (accepted, fixed, commented, or rejected).",
            "tags": "Tags applied to the task.",
            "unique_id": "Customer-supplied unique identifier used to deduplicate task creation.",
        },
    },
    "batches": {
        "description": "A collection of tasks grouped for calibration and delivery within a project.",
        "docs_url": "https://scale.com/docs/api-reference/batches",
        "columns": {
            "name": "Unique name of the batch.",
            "project": "Name of the project the batch belongs to.",
            "status": "Current status of the batch (staging, in_progress, or completed).",
            "created_at": "When the batch was created.",
            "completed_at": "When the batch was completed, if it has been.",
            "metadata": "Arbitrary customer-supplied metadata attached to the batch.",
        },
    },
    "projects": {
        "description": "A container that defines the labeling task type and instructions shared by its tasks and batches.",
        "docs_url": "https://scale.com/docs/api-reference/projects",
        "columns": {
            "name": "Unique name of the project.",
            "type": "The task type the project produces.",
            "created_at": "When the project was created.",
            "param_history": "History of parameter/instruction versions for the project.",
        },
    },
}
