from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Sourced from the Unstructured Platform API reference (https://docs.unstructured.io/api-reference).
# Keyed by the endpoint/schema name returned from `get_schemas`.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflows": {
        "description": "Workflows that define how Unstructured ingests, processes, and routes documents from sources to destinations.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/workflows",
        "columns": {
            "id": "Unique identifier of the workflow.",
            "name": "Human-readable name of the workflow.",
            "key": "Optional stable key for the workflow.",
            "sources": "Identifiers of the source connectors the workflow reads from.",
            "destinations": "Identifiers of the destination connectors the workflow writes to.",
            "workflow_type": "How the workflow was configured (e.g. platform, advanced, custom).",
            "workflow_nodes": "Ordered processing nodes (partition, chunk, embed, ...) that make up the workflow DAG.",
            "schedule": "Schedule on which the workflow runs automatically, if any.",
            "status": "Whether the workflow is active or inactive.",
            "created_at": "Timestamp when the workflow was created.",
            "updated_at": "Timestamp when the workflow was last updated.",
            "reprocess_all": "Whether the workflow reprocesses all files on each run.",
        },
    },
    "jobs": {
        "description": "Individual runs of a workflow at a point in time, including status and runtime.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/jobs",
        "columns": {
            "id": "Unique identifier of the job.",
            "workflow_id": "Identifier of the workflow this job ran.",
            "workflow_name": "Name of the workflow this job ran.",
            "status": "Current status of the job (e.g. scheduled, in progress, completed, failed).",
            "created_at": "Timestamp when the job was created.",
            "runtime": "Duration the job has run for.",
            "input_file_ids": "Identifiers of the input files processed by the job.",
            "output_node_files": "Metadata for the output files produced by each processing node.",
            "job_type": "Type of job run (e.g. ephemeral, persistent).",
        },
    },
    "sources": {
        "description": "Source connectors that ingest files or data into Unstructured from an external location.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/sources",
        "columns": {
            "id": "Unique identifier of the source connector.",
            "name": "Human-readable name of the source connector.",
            "type": "Connector type (e.g. s3, google_drive, salesforce).",
            "config": "Connector-specific configuration (connection details, excluding secrets).",
            "created_at": "Timestamp when the source connector was created.",
            "updated_at": "Timestamp when the source connector was last updated.",
            "key": "Optional stable key for the source connector.",
        },
    },
    "destinations": {
        "description": "Destination connectors that send Unstructured's processed data to an external location.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/destinations",
        "columns": {
            "id": "Unique identifier of the destination connector.",
            "name": "Human-readable name of the destination connector.",
            "type": "Connector type (e.g. s3, pinecone, snowflake).",
            "config": "Connector-specific configuration (connection details, excluding secrets).",
            "created_at": "Timestamp when the destination connector was created.",
            "updated_at": "Timestamp when the destination connector was last updated.",
            "key": "Optional stable key for the destination connector.",
        },
    },
    "job_details": {
        "description": "Processing details of each job: per-node document counts, overall outcome, and progress.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/jobs",
        "columns": {
            "id": "Unique identifier of the job.",
            "workflow_id": "Identifier of the workflow this job ran.",
            "job_created_at": "Timestamp when the job was created.",
            "processing_status": "Document-level outcome of the job (e.g. SUCCESS, COMPLETED_WITH_ERRORS, FAILED).",
            "node_stats": "Per-node document counts (ready, in progress, success, failure) for each step of the workflow DAG.",
            "summary": "Totals of documents processed, succeeded, and failed across the job.",
            "message": "Human-readable message about the job's processing state.",
            "progress": "Advisory reading of why the job is not finished yet, including when its steps last reported.",
            "queued_behind_job_ids_snapshot": "Jobs that held the workspace's concurrency slots when this job was queued.",
            "completion_issue": "Why a job completed without delivering a document, if an issue was detected.",
        },
    },
    "job_failed_files": {
        "description": "Files that failed to process in a job, with the workflow node that failed each one and the error.",
        "docs_url": "https://docs.unstructured.io/api-reference/workflow/jobs",
        "columns": {
            "job_id": "Identifier of the job the file failed in.",
            "workflow_id": "Identifier of the workflow the job ran.",
            "job_created_at": "Timestamp when the job was created.",
            "document": "The file that failed to process.",
            "error": "Error message for the failure.",
            "node": "The workflow node that failed the file (id, name, type, and subtype).",
            "node_id": "Identifier of the workflow node that failed the file.",
        },
    },
    "notifications": {
        "description": "Platform notification events, such as a job that started, completed, or failed.",
        "docs_url": "https://docs.unstructured.io/api-reference",
        "columns": {
            "id": "Unique identifier of the notification event.",
            "event_type": "Event type (e.g. job.completed, job.failed).",
            "workflow_id": "Workflow the event relates to; null for account-level events.",
            "payload": "Event payload data.",
            "created_at": "Timestamp when the event was created.",
            "is_read": "Whether the user that owns the API key marked the notification as read.",
        },
    },
}
