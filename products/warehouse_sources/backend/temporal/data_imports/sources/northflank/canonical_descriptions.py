from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions sourced from the public Northflank API reference (https://northflank.com/docs/v1/api).
# Fan-out child tables carry a `projectId` column injected by the transport so the row can be tied
# back to its parent project.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "A Northflank project — the top-level container that groups services, jobs, addons, and volumes.",
        "docs_url": "https://northflank.com/docs/v1/api/team/projects/list-projects",
        "columns": {
            "id": "Identifier for the project.",
            "name": "The name of the project.",
            "description": "A short description of the project.",
        },
    },
    "services": {
        "description": "A deployable unit within a project (a combined, build, or deployment service).",
        "docs_url": "https://northflank.com/docs/v1/api/project/services/list-services",
        "columns": {
            "id": "Identifier for the service.",
            "projectId": "Identifier of the project the service belongs to.",
            "appId": "Full identifier used for service deployment.",
            "name": "The name of the service.",
            "tags": "User-defined tags applied to the service.",
            "description": "A short description of the service.",
            "serviceType": "The service type: combined, build, or deployment.",
            "disabledCI": "Whether continuous integration is disabled for the service.",
            "disabledCD": "Whether continuous deployment is disabled for the service.",
            "status": "Build and deployment status of the service.",
        },
    },
    "jobs": {
        "description": "A manual or cron job defined within a project.",
        "docs_url": "https://northflank.com/docs/v1/api/project/jobs/list-jobs",
        "columns": {
            "id": "Identifier for the job.",
            "projectId": "Identifier of the project the job belongs to.",
            "appId": "Full identifier used for job deployment.",
            "name": "The name of the job.",
            "tags": "User-defined tags applied to the job.",
            "description": "A short description of the job.",
            "jobType": "The job type: manual or cron.",
            "disabledCI": "Whether continuous integration is disabled for the job.",
            "disabledCD": "Whether continuous deployment is disabled for the job.",
            "suspended": "Whether the job is suspended.",
        },
    },
    "addons": {
        "description": "A managed addon (e.g. a database) provisioned within a project.",
        "docs_url": "https://northflank.com/docs/v1/api/project/addons/list-addons",
        "columns": {
            "id": "Identifier for the addon.",
            "projectId": "Identifier of the project the addon belongs to.",
            "appId": "Full identifier used for the addon.",
            "name": "The name of the addon.",
            "tags": "User-defined tags applied to the addon.",
            "description": "A short description of the addon.",
            "spec": "The addon specification, including its type.",
            "status": "The current status of the addon.",
        },
    },
    "volumes": {
        "description": "A persistent volume provisioned within a project.",
        "docs_url": "https://northflank.com/docs/v1/api/project/volumes/list-volumes",
        "columns": {
            "id": "Identifier for the volume.",
            "projectId": "Identifier of the project the volume belongs to.",
            "name": "The name of the volume.",
            "tags": "User-defined tags applied to the volume.",
            "spec": "The volume specification (access mode, storage class, and size).",
            "attachedObjects": "Objects the volume is attached to.",
            "status": "The current status of the volume.",
            "createdAt": "When the volume was created.",
            "updatedAt": "When the volume was last updated.",
        },
    },
}
