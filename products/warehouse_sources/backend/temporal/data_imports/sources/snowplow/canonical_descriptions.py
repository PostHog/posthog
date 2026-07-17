from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Snowplow BDP Console API OpenAPI spec
# (https://console.snowplowanalytics.com/api/msc/v1/docs/docs.yaml).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pipelines": {
        "description": "The Snowplow pipelines in your organization.",
        "docs_url": "https://docs.snowplow.io/docs/using-the-snowplow-console/managing-console-api-authentication/",
        "columns": {
            "id": "UUID of the pipeline.",
            "name": "Name of the pipeline.",
            "status": "Deployment status of the pipeline stack.",
            "label": "Pipeline label (e.g. production, sandbox).",
            "workspaceId": "UUID of the workspace the pipeline belongs to.",
        },
    },
    "users": {
        "description": "Users of your Snowplow BDP Console organization.",
        "docs_url": "https://docs.snowplow.io/docs/using-the-snowplow-console/managing-users/",
        "columns": {
            "id": "UUID of the user.",
            "email": "Email address of the user.",
            "organizationId": "UUID of the organization the user belongs to.",
            "firstName": "First name of the user.",
            "lastName": "Last name of the user.",
            "jobTitle": "Job title of the user.",
            "lastLogin": "When the user last logged in to the Console.",
            "permissions": "Permission sets granted to the user, as capability objects.",
        },
    },
    "data_models": {
        "description": "Data models (dbt or SQL Runner) configured to run against your warehouse.",
        "docs_url": "https://docs.snowplow.io/docs/modeling-your-data/running-data-models-via-snowplow-bdp/",
        "columns": {
            "name": "Name of the data model.",
            "description": "Description of the data model.",
            "status": "Whether the data model is enabled or disabled.",
            "owners": "Email addresses of the model's owners.",
            "schedules": "Cron schedules the model runs on.",
            "runner": "The runner executing the model (dbt or sql-runner).",
            "runnerVersion": "Version of the runner.",
            "changeLog": "History of changes made to the model configuration.",
        },
    },
    "data_structures": {
        "description": "Data structures (event and entity schemas) registered in your organization, with the most recent deployment per environment.",
        "docs_url": "https://docs.snowplow.io/docs/understanding-tracking-design/managing-your-data-structures/api/",
        "columns": {
            "hash": "Stable hash identifying the data structure.",
            "organizationId": "UUID of the organization the data structure belongs to.",
            "vendor": "Vendor of the schema (e.g. com.acme).",
            "name": "Name of the schema.",
            "format": "Schema format (e.g. jsonschema).",
            "deployments": "Most recent deployment of the schema per environment.",
        },
    },
    "job_runs": {
        "description": "Executions of data modeling jobs. Snowplow retains only about the preceding week of run history.",
        "docs_url": "https://docs.snowplow.io/docs/modeling-your-data/running-data-models-via-snowplow-bdp/retrieving-job-execution-data-via-the-api/",
        "columns": {
            "runId": "Unique identifier of the job run.",
            "jobId": "Identifier of the job this run belongs to.",
            "jobName": "Name of the job (e.g. the data model name).",
            "environment": "Environment the job ran against.",
            "state": "Run state: FAILED, RUNNING, SKIPPED, SUCCEEDED, or WAITING.",
            "startTime": "When the run started.",
            "duration": "Duration of the run (ISO 8601 duration).",
            "failureReason": "Reason the run failed, when it did.",
        },
    },
    "job_run_steps": {
        "description": "Per-step execution detail for each data modeling job run, one row per (run, step).",
        "docs_url": "https://docs.snowplow.io/docs/modeling-your-data/running-data-models-via-snowplow-bdp/retrieving-job-execution-data-via-the-api/",
        "columns": {
            "runId": "Identifier of the job run the step belongs to.",
            "name": "Name of the step.",
            "state": "Step state: FAILED, RUNNING, SKIPPED, SUCCEEDED, SUCCEEDED_NO_OP, or WAITING.",
            "dependencies": "Names of the steps this step depends on.",
            "duration": "Duration of the step (ISO 8601 duration).",
            "jobId": "Identifier of the job the parent run belongs to.",
            "jobName": "Name of the job the parent run belongs to.",
            "environment": "Environment the parent run ran against.",
            "runStartTime": "When the parent run started.",
        },
    },
    "failed_event_metrics": {
        "description": "Failed-event counts per pipeline, error, and time bucket, for monitoring data quality.",
        "docs_url": "https://docs.snowplow.io/docs/managing-data-quality/monitoring-failed-events/",
        "columns": {
            "pipelineId": "UUID of the pipeline the failed events occurred on.",
            "errorId": "Identifier of the failed-event error.",
            "schemaKey": "Schema of the events that failed.",
            "classification": "Failure classification: Enrichment or Validation.",
            "window": "Start of the time bucket the count applies to.",
            "count": "Number of failed events in the bucket.",
            "lastSeen": "When a failed event for this error was last seen in the bucket.",
        },
    },
}
