from typing import Any

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
    describe_key: str | None = None
    list_filters: tuple[tuple[str, str], ...] = ()

    def describe_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {self.name_field: item[self.describe_key or self.name_field]}


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
    "endpoint_configs": SageMakerEndpoint(
        list_operation="ListEndpointConfigs",
        result_key="EndpointConfigs",
        describe_operation="DescribeEndpointConfig",
        name_field="EndpointConfigName",
        primary_key="endpoint_config_arn",
        incremental=True,
    ),
    "model_packages": SageMakerEndpoint(
        list_operation="ListModelPackages",
        result_key="ModelPackageSummaryList",
        describe_operation="DescribeModelPackage",
        name_field="ModelPackageName",
        primary_key="model_package_arn",
        # Versioned packages share their group's name, so only the ARN identifies one version.
        describe_key="ModelPackageArn",
        # The API lists only unversioned packages by default, which hides Model Registry versions.
        list_filters=(("ModelPackageType", "Both"),),
    ),
    "hyperparameter_tuning_jobs": SageMakerEndpoint(
        list_operation="ListHyperParameterTuningJobs",
        result_key="HyperParameterTuningJobSummaries",
        describe_operation="DescribeHyperParameterTuningJob",
        name_field="HyperParameterTuningJobName",
        primary_key="hyper_parameter_tuning_job_arn",
    ),
    "automl_jobs": SageMakerEndpoint(
        list_operation="ListAutoMLJobs",
        result_key="AutoMLJobSummaries",
        describe_operation="DescribeAutoMLJobV2",
        name_field="AutoMLJobName",
        primary_key="auto_ml_job_arn",
    ),
}

# Mutable resources cannot sort by modification time, so creation cursors would miss later changes.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "models": [incremental_field("creation_time")],
    "endpoint_configs": [incremental_field("creation_time")],
}
ENDPOINT_DESCRIPTIONS = {
    "training_jobs": "Training jobs with status, resource settings, metrics, and billable duration.",
    "processing_jobs": "Processing jobs with status, input and output settings, and compute resources.",
    "endpoints": "Inference endpoints with status, deployment settings, and production variants.",
    "models": "Models with container settings, execution roles, and creation times.",
    "endpoint_configs": "Endpoint configurations with production variants, instance types, and data capture settings.",
    "model_packages": "Model packages and Model Registry versions with approval status, metrics, and inference settings.",
    "hyperparameter_tuning_jobs": "Hyperparameter tuning jobs with objectives, best training jobs, and consumed resources.",
    "automl_jobs": "AutoML jobs with problem type, objective, status, and best candidate.",
}
