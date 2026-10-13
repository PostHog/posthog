from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "job_attempts": {
        "description": (
            "One row per attempt of a Depot CI job, with the context of its run, workflow, and job. "
            "Jobs that never ran, such as skipped jobs and matrix expansion placeholders, have no rows."
        ),
        "docs_url": "https://depot.dev/docs/api/ci/reference",
        "columns": {
            "run_id": "Unique identifier of the Depot CI run.",
            "run_workflow_count": "Number of workflows the run started.",
            "repo": "GitHub repository of the run, as owner/name.",
            "ref": "Git ref the run was triggered for.",
            "sha": "Commit SHA of the run.",
            "head_sha": "Head commit SHA reported for the run.",
            "trigger": "Event that triggered the run.",
            "run_status": "Terminal status of the run: finished, failed, or cancelled.",
            "run_created_at": "Time the run was created, as an RFC 3339 timestamp.",
            "run_started_at": "Time the run started, as an RFC 3339 timestamp.",
            "run_finished_at": "Time the run finished, as an RFC 3339 timestamp.",
            "workflow_id": "Unique identifier of the workflow within the run.",
            "workflow_name": "Name of the workflow.",
            "workflow_path": "Path of the workflow file in the repository.",
            "workflow_status": "Status of the workflow.",
            "workflow_created_at": "Time the workflow was created, as an RFC 3339 timestamp.",
            "workflow_started_at": "Time the workflow started, as an RFC 3339 timestamp.",
            "workflow_finished_at": "Time the workflow finished, as an RFC 3339 timestamp.",
            "job_id": "Unique identifier of the job.",
            "job_key": "Key of the job, as workflow file and job ID, for example ci-backend.yml:turbo-tests:matrix-38 for a matrix cell.",
            "job_display_name": "Human-readable job name, including matrix values.",
            "job_status": "Status of the job: finished, failed, cancelled or skipped.",
            "job_started_at": "Time the job started, as an RFC 3339 timestamp.",
            "job_finished_at": "Time the job finished, as an RFC 3339 timestamp.",
            "attempt_id": "Unique identifier of the job attempt.",
            "attempt": "Attempt number of the job.",
            "attempt_status": "Status of the attempt: finished, failed or cancelled.",
            "attempt_started_at": "Time the attempt started, as an RFC 3339 timestamp.",
            "attempt_finished_at": "Time the attempt finished, as an RFC 3339 timestamp.",
            "sandbox_id": "Identifier of the sandbox that ran the attempt.",
        },
    },
}
