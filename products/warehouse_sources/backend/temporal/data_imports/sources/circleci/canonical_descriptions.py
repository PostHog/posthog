"""Canonical, documentation-sourced descriptions for CircleCI endpoints and columns.

Sourced from the official CircleCI API v2 reference (https://circleci.com/docs/api/v2/).
Keyed by the endpoint names in `settings.py` `CIRCLECI_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced CircleCI table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pipelines": {
        "description": "A CircleCI pipeline — the full unit of work triggered for a project on a commit.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/listPipelines",
        "columns": {
            "id": "Unique identifier for the pipeline.",
            "number": "Sequential number of the pipeline within its project.",
            "project_slug": "Project slug the pipeline belongs to, in vcs/org/repo format.",
            "state": "State of the pipeline (created, errored, setup-pending, setup, or pending).",
            "created_at": "Time at which the pipeline was created.",
            "updated_at": "Time at which the pipeline was last updated.",
            "trigger": "Information about what triggered the pipeline (e.g. webhook, api, schedule).",
            "vcs": "Version control details for the pipeline (branch, revision, commit).",
            "errors": "Any errors that occurred while creating the pipeline.",
        },
    },
    "workflows": {
        "description": "A workflow — a configured run of jobs within a pipeline.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/listWorkflowsByPipelineId",
        "columns": {
            "id": "Unique identifier for the workflow.",
            "name": "Name of the workflow as defined in the project config.",
            "pipeline_id": "Identifier of the pipeline the workflow belongs to.",
            "pipeline_number": "Number of the pipeline the workflow belongs to.",
            "project_slug": "Project slug the workflow belongs to, in vcs/org/repo format.",
            "status": "Status of the workflow (e.g. success, running, failed, error, canceled).",
            "created_at": "Time at which the workflow was created.",
            "stopped_at": "Time at which the workflow stopped.",
            "started_by": "Identifier of the user who started the workflow.",
        },
    },
    "jobs": {
        "description": "A job within a workflow — a single execution unit with steps.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/listWorkflowJobs",
        "columns": {
            "id": "Unique identifier for the job.",
            "name": "Name of the job as defined in the project config.",
            "job_number": "Number of the job within its project.",
            "type": "Type of the job (build or approval).",
            "status": "Status of the job (e.g. success, running, failed, blocked, canceled).",
            "started_at": "Time at which the job started.",
            "stopped_at": "Time at which the job stopped.",
            "project_slug": "Project slug the job belongs to, in vcs/org/repo format.",
            "dependencies": "Identifiers of jobs this job depends on.",
        },
    },
    "projects": {
        "description": "A CircleCI project — a repository configured to build on CircleCI.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/getProjectBySlug",
        "columns": {
            "id": "Unique identifier for the project.",
            "slug": "Project slug in vcs/org/repo format.",
            "name": "Name of the project (typically the repository name).",
            "organization_name": "Name of the organization the project belongs to.",
            "organization_slug": "Slug of the organization the project belongs to.",
            "organization_id": "Identifier of the organization the project belongs to.",
            "vcs_info": "Version control details for the project (provider, default branch, URL).",
        },
    },
    "components": {
        "description": "A deployed component — a deployable unit of a project tracked by CircleCI releases.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/listComponents",
        "columns": {
            "id": "Unique identifier for the component.",
            "name": "Name of the component.",
            "project_id": "Identifier of the project the component belongs to.",
            "labels": "Key/value labels associated with the component.",
            "release_count": "Number of releases recorded for the component.",
            "created_at": "Time at which the component was created.",
            "updated_at": "Time at which the component was last updated.",
        },
    },
    "component_versions": {
        "description": "A version of a component deployed to an environment, one row per deploy target.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/listComponentVersions",
        "columns": {
            "component_id": "Identifier of the component the version belongs to.",
            "name": "Version name, for example 1.0.0.",
            "environment_id": "Identifier of the environment the version was deployed to.",
            "namespace": "Namespace the version was deployed in.",
            "is_live": "Whether the version is currently live.",
            "pipeline_id": "Identifier of the pipeline that deployed the version.",
            "workflow_id": "Identifier of the workflow that deployed the version.",
            "job_id": "Identifier of the job that deployed the version.",
            "job_number": "Number of the job that deployed the version.",
            "last_deployed_at": "Time at which the version was last deployed.",
        },
    },
    "users": {
        "description": "A CircleCI user referenced as the actor on a workflow.",
        "docs_url": "https://circleci.com/docs/api/v2/#operation/getUser",
        "columns": {
            "id": "Unique identifier for the user.",
            "login": "Login of the user on the version control provider.",
            "name": "Name of the user.",
            "avatar_url": "URL of the user's avatar on the version control provider.",
        },
    },
}
