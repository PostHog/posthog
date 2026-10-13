from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "deployments": {
        "description": "Airflow environments in an Astro organization.",
        "docs_url": "https://www.astronomer.io/docs/astro/api/v-1/api-reference/deployment/list-deployments",
        "columns": {
            "id": "The identifier of the deployment.",
            "name": "The deployment name.",
            "createdAt": "The time when the deployment was created, in UTC.",
            "updatedAt": "The time when the deployment was last updated, in UTC.",
        },
    },
    "deploys": {
        "description": "Code and image deploys for each Astro deployment.",
        "docs_url": "https://www.astronomer.io/docs/astro/api/v-1/api-reference/deploy/list-deploys",
        "columns": {
            "id": "The identifier of the deploy.",
            "deploymentId": "The identifier of the deployment that received the deploy.",
            "createdAt": "The time when the deploy was created, in UTC.",
            "status": "The deploy status: INITIALIZED, DEPLOYED, or FAILED.",
            "type": "The deploy type: IMAGE_AND_DAG, IMAGE_ONLY, or DAG_ONLY.",
            "airflowVersion": "The Airflow version used by the deploy.",
            "astroRuntimeVersion": "The Astro Runtime version used by the deploy.",
            "imageTag": "The image tag for the deploy.",
        },
    },
    "workspaces": {
        "description": "Groups of deployments in an Astro organization.",
        "docs_url": "https://www.astronomer.io/docs/astro/api/api-reference/workspace/list-workspaces",
        "columns": {
            "id": "The identifier of the workspace.",
            "name": "The workspace name.",
            "organizationId": "The identifier of the organization that owns the workspace.",
            "createdAt": "The time when the workspace was created, in UTC.",
            "updatedAt": "The time when the workspace was last updated, in UTC.",
        },
    },
    "clusters": {
        "description": "Kubernetes clusters that host Astro deployments.",
        "docs_url": "https://www.astronomer.io/docs/astro/api/v-1/api-reference/cluster/list-clusters",
        "columns": {
            "id": "The identifier of the cluster.",
            "name": "The cluster name.",
            "cloudProvider": "The cloud provider that hosts the cluster.",
            "region": "The region where the cluster was created.",
            "status": "The cluster status.",
            "createdAt": "The time when the cluster was created, in UTC.",
            "updatedAt": "The time when the cluster was last updated, in UTC.",
        },
    },
}
