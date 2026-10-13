from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

SAGEMAKER_API_VERSION = "2017-07-24"
TARGET_PREFIXES = {SAGEMAKER_API_VERSION: "SageMaker"}
MAX_RESULTS = 100


@frozen
class SageMakerEndpoint:
    list_operation: str
    result_key: str
    describe_operation: str
    name_field: str
    primary_key: str
    incremental: bool = False


ENDPOINTS: dict[str, SageMakerEndpoint] = {
    "training_jobs": SageMakerEndpoint(
        list_operation="ListTrainingJobs",
        result_key="TrainingJobSummaries",
        describe_operation="DescribeTrainingJob",
        name_field="TrainingJobName",
        primary_key="training_job_arn",
    ),
    "processing_jobs": SageMakerEndpoint(
        list_operation="ListProcessingJobs",
        result_key="ProcessingJobSummaries",
        describe_operation="DescribeProcessingJob",
        name_field="ProcessingJobName",
        primary_key="processing_job_arn",
    ),
    "endpoints": SageMakerEndpoint(
        list_operation="ListEndpoints",
        result_key="Endpoints",
        describe_operation="DescribeEndpoint",
        name_field="EndpointName",
        primary_key="endpoint_arn",
    ),
    "models": SageMakerEndpoint(
        list_operation="ListModels",
        result_key="Models",
        describe_operation="DescribeModel",
        name_field="ModelName",
        primary_key="model_arn",
        incremental=True,
    ),
}

# Mutable resources cannot sort by modification time, so creation cursors would miss later changes.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {"models": [incremental_field("creation_time")]}
ENDPOINT_DESCRIPTIONS = {
    "training_jobs": "Training jobs with status, resource settings, metrics, and billable duration.",
    "processing_jobs": "Processing jobs with status, input and output settings, and compute resources.",
    "endpoints": "Inference endpoints with status, deployment settings, and production variants.",
    "models": "Models with container settings, execution roles, and creation times.",
}
