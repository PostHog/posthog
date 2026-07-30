from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "applications": {
        "description": "Argo CD applications with their sync state, health, and full desired/live specification.",
        "docs_url": "https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#applications",
        "columns": {
            "name": "Name of the application.",
            "namespace": "Kubernetes namespace the Application resource lives in (usually the Argo CD control-plane namespace).",
            "uid": "Kubernetes UID of the Application resource; changes if the application is deleted and recreated.",
            "created_at": "Timestamp the Application resource was created.",
            "project": "Argo CD project the application belongs to.",
            "sync_status": "Whether the live state matches the desired Git state (Synced, OutOfSync, or Unknown).",
            "health_status": "Aggregated health of the application's resources (Healthy, Progressing, Degraded, Suspended, Missing, or Unknown).",
            "metadata": "Full Kubernetes object metadata (labels, annotations, finalizers).",
            "spec": "Desired application state: source repository, target revision, destination cluster/namespace, and sync policy.",
            "status": "Observed application state: resources, conditions, sync/health details, and deployment history.",
            "operation": "Currently requested sync operation, if one is in flight.",
        },
    },
    "deployment_history": {
        "description": "One row per recorded deployment, flattened from each application's status.history. Useful for DORA metrics such as deployment frequency.",
        "docs_url": "https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_app_history/",
        "columns": {
            "application_name": "Name of the application that was deployed.",
            "application_namespace": "Namespace of the Application resource.",
            "application_uid": "Kubernetes UID of the Application resource.",
            "project": "Argo CD project the application belongs to.",
            "id": "History entry id, incremented per application on each deployment.",
            "revision": "Git revision (commit SHA) that was deployed.",
            "revisions": "Git revisions deployed, for applications with multiple sources.",
            "deployed_at": "Timestamp the deployment finished.",
            "deploy_started_at": "Timestamp the deployment started.",
            "source": "Application source (repository URL, path, target revision) at deployment time.",
            "sources": "Application sources at deployment time, for applications with multiple sources.",
            "initiated_by": "Who or what triggered the deployment (user or automated sync).",
        },
    },
    "projects": {
        "description": "Argo CD projects (AppProject resources), which group applications and restrict their sources and destinations.",
        "docs_url": "https://argo-cd.readthedocs.io/en/stable/user-guide/projects/",
        "columns": {
            "name": "Name of the project.",
            "uid": "Kubernetes UID of the AppProject resource.",
            "created_at": "Timestamp the project was created.",
            "metadata": "Full Kubernetes object metadata (labels, annotations).",
            "spec": "Project configuration: allowed source repositories, destinations, cluster resource whitelists, and roles.",
            "status": "Observed project state, e.g. jwt token metadata per role.",
        },
    },
    "repositories": {
        "description": "Git and Helm repositories connected to Argo CD. Credential fields are never synced.",
        "docs_url": "https://argo-cd.readthedocs.io/en/stable/user-guide/private-repositories/",
        "columns": {
            "repo": "Repository URL.",
            "name": "Display name of the repository.",
            "project": "Argo CD project the repository is scoped to, if any.",
            "type": "Repository type (git or helm).",
            "connectionState": "Result of Argo CD's most recent connectivity check for the repository.",
        },
    },
    "clusters": {
        "description": "Kubernetes clusters Argo CD deploys to. Connection credentials are never synced.",
        "docs_url": "https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters",
        "columns": {
            "server": "Kubernetes API server URL of the cluster.",
            "name": "Display name of the cluster.",
            "namespaces": "Namespaces Argo CD is allowed to manage in the cluster.",
            "connectionState": "Result of Argo CD's most recent connectivity check for the cluster.",
            "serverVersion": "Kubernetes version of the cluster.",
            "info": "Cluster statistics such as application count and cache state.",
        },
    },
}
