from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "pipelines": {
        "description": "Pipeline summaries in the selected Harness project.",
        "docs_url": "https://apidocs.harness.io/pipeline/getpipelinelist",
        "columns": {
            "identifier": "Pipeline identifier within the project.",
            "name": "Pipeline name.",
            "createdAt": "Creation time in milliseconds since the Unix epoch.",
            "lastUpdatedAt": "Last update time in milliseconds since the Unix epoch.",
            "numOfStages": "Number of stages in the pipeline.",
            "modules": "Harness modules used by the pipeline.",
        },
    },
    "executions": {
        "description": "Pipeline executions, including status, timing, and stage counts.",
        "docs_url": "https://apidocs.harness.io/pipeline-execution-details/getlistofexecutions",
        "columns": {
            "planExecutionId": "Unique identifier of the pipeline execution.",
            "pipelineIdentifier": "Identifier of the pipeline that ran.",
            "status": "Execution status.",
            "startTs": "Execution start time in milliseconds since the Unix epoch.",
            "endTs": "Execution end time in milliseconds since the Unix epoch.",
            "createdAt": "Creation time in milliseconds since the Unix epoch.",
            "runSequence": "Sequence number of the pipeline run.",
            "failedStagesCount": "Number of failed stages.",
        },
    },
    "services": {
        "description": "Services configured for deployment in the selected Harness project.",
        "docs_url": "https://apidocs.harness.io/services/getservicelist",
        "columns": {
            "identifier": "Service identifier within the project.",
            "name": "Service name.",
            "createdAt": "Creation time in milliseconds since the Unix epoch.",
            "lastModifiedAt": "Last modification time in milliseconds since the Unix epoch.",
            "orgIdentifier": "Organization identifier.",
            "projectIdentifier": "Project identifier.",
        },
    },
    "environments": {
        "description": "Deployment environments in the selected Harness project.",
        "docs_url": "https://apidocs.harness.io/environments/getenvironmentlist",
        "columns": {
            "identifier": "Environment identifier within the project.",
            "name": "Environment name.",
            "type": "Production or preproduction environment type.",
            "createdAt": "Creation time in milliseconds since the Unix epoch.",
            "lastModifiedAt": "Last modification time in milliseconds since the Unix epoch.",
        },
    },
}
