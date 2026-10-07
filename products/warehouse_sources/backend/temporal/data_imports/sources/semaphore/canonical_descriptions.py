from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "Workflow runs for the selected Semaphore project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-workflows",
        "columns": {
            "wf_id": "Unique workflow identifier.",
            "project_id": "Project that owns the workflow.",
            "created_at": "Workflow creation time in UTC.",
            "initial_ppl_id": "Identifier of the first pipeline.",
            "commit_sha": "Git commit for the workflow.",
            "branch_name": "Git branch for the workflow.",
        },
    },
    "pipelines": {
        "description": "Pipelines and their execution states for the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-pipelines",
        "columns": {
            "ppl_id": "Unique pipeline identifier.",
            "wf_id": "Workflow that contains the pipeline.",
            "state": "Pipeline execution state.",
            "result": "Pipeline result after execution ends.",
            "created_at": "Pipeline creation time in UTC.",
        },
    },
    "deployment_targets": {
        "description": "Deployment targets configured for the selected project.",
        "docs_url": "https://docs.semaphore.io/reference/api#list-targets",
        "columns": {
            "id": "Unique deployment target identifier.",
            "project_id": "Project that owns the target.",
            "name": "Deployment target name.",
            "created_at": "Target creation time in UTC.",
        },
    },
}
