from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "environments": {
        "description": "Scalr environments group related workspaces and share policies and configuration.",
        "docs_url": "https://docs.scalr.io/reference/list_environments",
        "columns": {
            "id": "Identifier of the environment.",
            "name": "Name of the environment.",
            "created_at": "Time when Scalr created the environment.",
            "updated_at": "Time of the last environment update.",
            "locked": "Whether the environment blocks runs from entering the queue.",
            "relationships": "References to the account and other related resources.",
        },
    },
    "workspaces": {
        "description": "Scalr workspaces contain infrastructure configuration, runs, and state files.",
        "docs_url": "https://docs.scalr.io/reference/get_workspaces",
        "columns": {
            "id": "Identifier of the workspace.",
            "name": "Workspace name, unique within its environment.",
            "created_at": "Time when Scalr created the workspace.",
            "updated_at": "Time of the last workspace update.",
            "auto_apply": "Whether a successful plan starts an apply automatically.",
            "relationships": "References to the environment, runs, and other related resources.",
        },
    },
    "runs": {
        "description": "Terraform and OpenTofu runs, including their current status and status transition times.",
        "docs_url": "https://docs.scalr.io/reference/get_runs",
        "columns": {
            "id": "Identifier of the run.",
            "created_at": "Time when Scalr created the run.",
            "status": "Current stage or final result of the run.",
            "status_timestamps": "Times when the run entered its current and previous states.",
            "has_changes": "Whether the plan proposes infrastructure changes.",
            "source": "Origin of the run.",
            "relationships": "References to the workspace, plan, apply, and other related resources.",
        },
    },
}
