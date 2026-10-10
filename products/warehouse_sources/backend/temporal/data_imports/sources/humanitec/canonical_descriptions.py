from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.humanitec.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "applications": {
        "description": "Applications group workloads that deploy together into an environment.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Application ID.",
            "org_id": "Organization that contains the application.",
            "name": "Application name.",
            "created_at": "Time when the application was created.",
            "envs": "Environments associated with the application.",
            "status": "Current application status.",
        },
    },
    "environments": {
        "description": "Environments provide independent spaces where applications run.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Environment ID within the application.",
            "app_id": "Application ID from the parent application.",
            "name": "Environment name.",
            "type": "Environment type used to group and manage environments.",
            "created_at": "Time when the environment was created.",
            "last_deploy": "Last deployment in the environment, if one exists.",
            "status": "Current environment status.",
        },
    },
    "deployments": {
        "description": "Deployments record changes to the running state of an environment.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Deployment ID.",
            "app_id": "Application ID from the parent application.",
            "env_id": "Environment where the deployment occurred.",
            "created_at": "Time when the deployment started.",
            "created_by": "User who started the deployment.",
            "status": "Deployment status: pending, in progress, succeeded, or failed.",
            "status_changed_at": "Time of the last status change. For completed deployments, this is the completion time.",
            "delta_id": "Delta that describes the deployment changes.",
            "set_id": "Deployment set that describes the resulting environment state.",
        },
    },
    "active_resources": {
        "description": "Active resources are infrastructure resources provisioned for an environment.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "gu_res_id": "Globally unique resource ID.",
            "app_id": "Application associated with the resource.",
            "env_id": "Environment associated with the resource.",
            "def_id": "Resource definition used to provision the resource.",
            "deploy_id": "Deployment that last provisioned the resource.",
            "type": "Resource type.",
            "status": "Current resource status: pending, active, or deleting.",
            "updated_at": "Time when a deployment last provisioned the resource.",
        },
    },
    "environment_types": {
        "description": "Environment types group environments for management and resource selection.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Environment type ID within the organization.",
            "description": "Description of the environment type.",
        },
    },
    "pipelines": {
        "description": "Pipelines define automated deployment workflows within an application.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Pipeline ID within the application.",
            "app_id": "Application that contains the pipeline.",
            "org_id": "Organization that contains the pipeline.",
            "name": "Pipeline name.",
            "status": "Current pipeline status.",
            "version": "ID of the current pipeline version.",
            "created_at": "Time when the pipeline was created.",
            "trigger_types": "Trigger types in the current pipeline schema.",
        },
    },
}
