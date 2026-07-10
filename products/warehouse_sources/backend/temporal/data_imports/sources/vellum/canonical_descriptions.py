from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Descriptions taken from Vellum's public API reference (https://docs.vellum.ai/api-reference).
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "workflow_deployments": {
        "description": "Deployed Vellum workflows, one row per workflow deployment in the environment the API key is scoped to.",
        "docs_url": "https://docs.vellum.ai/api-reference/api-reference/workflow-deployments/list",
        "columns": {
            "id": "Vellum-generated ID that uniquely identifies this workflow deployment.",
            "name": "A name that uniquely identifies this workflow deployment within its workspace.",
            "label": "A human-readable label for the workflow deployment.",
            "status": "The current status of the workflow deployment (ACTIVE, ARCHIVED, or PENDING_DELETION).",
            "environment": "Deprecated. The value returned will always be 'PRODUCTION'.",
            "created": "Timestamp representing when this workflow deployment was created.",
            "last_deployed_on": "Timestamp representing when this workflow deployment was most recently deployed.",
            "input_variables": "The input variables this workflow deployment expects when executed.",
            "output_variables": "The output variables this workflow deployment produces when executed.",
            "description": "A human-readable description of the workflow deployment.",
        },
    },
    "prompt_deployments": {
        "description": "Deployed Vellum prompts, one row per prompt deployment in the environment the API key is scoped to.",
        "docs_url": "https://docs.vellum.ai/api-reference/api-reference/deployments/list",
        "columns": {
            "id": "Vellum-generated ID that uniquely identifies this prompt deployment.",
            "name": "A name that uniquely identifies this deployment within its workspace.",
            "label": "A human-readable label for the deployment.",
            "status": "The current status of the deployment (ACTIVE, ARCHIVED, or PENDING_DELETION).",
            "environment": "Deprecated. The value returned will always be 'PRODUCTION'.",
            "created": "Timestamp representing when this deployment was created.",
            "last_deployed_on": "Timestamp representing when this deployment was most recently deployed.",
            "input_variables": "The input variables this deployment expects when executed.",
            "description": "A human-readable description of the deployment.",
        },
    },
    "document_indexes": {
        "description": "RAG document indexes used to store and search over uploaded documents.",
        "docs_url": "https://docs.vellum.ai/api-reference/api-reference/document-indexes/list",
        "columns": {
            "id": "Vellum-generated ID that uniquely identifies this document index.",
            "name": "A name that uniquely identifies this index within its workspace.",
            "label": "A human-readable label for the document index.",
            "status": "The current status of the document index (ACTIVE, ARCHIVED, or PENDING_DELETION).",
            "created": "Timestamp representing when this document index was created.",
            "indexing_config": "The configuration used to chunk, embed, and index documents in this index.",
        },
    },
    "documents": {
        "description": "Documents uploaded to Vellum for indexing and retrieval.",
        "docs_url": "https://docs.vellum.ai/api-reference/api-reference/documents/list",
        "columns": {
            "id": "Vellum-generated ID that uniquely identifies this document.",
            "external_id": "The external ID that was originally provided when uploading the document.",
            "last_uploaded_at": "Timestamp representing when this document was most recently uploaded.",
            "label": "Human-friendly name for this document.",
            "processing_state": "The current processing state of the document.",
            "processing_failure_reason": "Why the document could not be processed. Null unless processing_state is FAILED.",
            "status": "The document's current status.",
            "keywords": "A list of keywords associated with this document, provided at upload time.",
            "metadata": "A JSON object of metadata that can be filtered on when searching.",
            "document_to_document_indexes": "The indexes this document has been added to, with per-index processing state.",
        },
    },
    "workflow_execution_events": {
        "description": "Per-execution history for each workflow deployment: inputs, outputs, timing, and errors for every run. One row per execution span, keyed by the parent workflow deployment and the span id.",
        "docs_url": "https://docs.vellum.ai/api-reference/api-reference/workflow-deployments/list-workflow-deployment-event-executions",
        "columns": {
            "workflow_deployment_id": "ID of the workflow deployment this execution belongs to (injected by PostHog during the fan-out).",
            "span_id": "Vellum-generated ID that uniquely identifies this execution span.",
            "start": "Timestamp representing when this execution started.",
            "end": "Timestamp representing when this execution finished. Null while still running.",
            "inputs": "The input values this execution was invoked with.",
            "outputs": "The output values this execution produced.",
            "error": "Error details if the execution failed.",
            "usage_results": "Token usage and cost information for the execution.",
            "parent_context": "Context about the parent that triggered this execution, if any.",
            "latest_actual": "The most recent actual/feedback value recorded against this execution.",
            "metric_results": "Metric evaluation results recorded for this execution.",
        },
    },
}
