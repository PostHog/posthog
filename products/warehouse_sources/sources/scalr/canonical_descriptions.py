from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "users": {
        "description": "IAM users who can sign in to the Scalr account.",
        "docs_url": "https://docs.scalr.io/reference/get_users",
        "columns": {
            "id": "Identifier of the user.",
            "email": "Email address of the user.",
            "full_name": "Full name of the user.",
            "username": "Username of the user.",
            "status": "Current status of the user.",
            "created_at": "Time when Scalr created the user.",
            "last_login_at": "Time of the last sign-in of the user.",
            "relationships": "References to the identity providers and teams of the user.",
        },
    },
    "plans": {
        "description": "Terraform and OpenTofu plan stages of runs, with the count of proposed resource changes.",
        "docs_url": "https://docs.scalr.io/reference/get_plan",
        "columns": {
            "id": "Identifier of the plan.",
            "status": "Current stage or final result of the plan.",
            "status_timestamps": "Times when the plan entered its current and previous states.",
            "has_changes": "Whether the plan proposes resource changes.",
            "resource_additions": "Number of resources that the plan adds.",
            "resource_changes": "Number of resources that the plan updates in place.",
            "resource_destructions": "Number of resources that the plan destroys.",
            "execution_details": "Details about where and how the plan ran.",
        },
    },
    "state_versions": {
        "description": "Versions of the Terraform state of each workspace. The state file itself is not imported.",
        "docs_url": "https://docs.scalr.io/reference/list_state_versions",
        "columns": {
            "id": "Identifier of the state version.",
            "created_at": "Time when Scalr created the state version.",
            "serial": "Serial number of the state version, from the state file.",
            "lineage": "Lineage of the state, from the state file.",
            "status": "Processing status of the state version.",
            "size": "Size of the state file in bytes.",
            "outputs": "Output values of the state. Sensitive values are removed.",
            "resources": "Resources in the state. Scalr marks this attribute as deprecated.",
            "relationships": "References to the workspace, run, and previous and next state versions.",
        },
    },
}
