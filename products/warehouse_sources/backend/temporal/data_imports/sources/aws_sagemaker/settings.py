from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

SAGEMAKER_API_VERSION = "2017-07-24"
TARGET_PREFIXES = {SAGEMAKER_API_VERSION: "SageMaker"}
MAX_RESULTS = 100


@frozen
class SageMakerParent:
    list_operation: str
    result_key: str
    name_field: str


@frozen
class SageMakerEndpoint:
    list_operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    # Without a describe operation, the list summary is the row.
    describe_operation: str | None = None
    name_field: str = ""
    incremental: bool = False
    describe_key: str | None = None
    list_filters: tuple[tuple[str, str], ...] = ()
    # The list operation requires a parent name, so the source lists each parent's children.
    parent: SageMakerParent | None = None

    def describe_payload(self, item: dict[str, Any]) -> dict[str, Any]:
        return {self.name_field: item[self.describe_key or self.name_field]}


ENDPOINTS: dict[str, SageMakerEndpoint] = {
    "training_jobs": SageMakerEndpoint(
        list_operation="ListTrainingJobs",
        result_key="TrainingJobSummaries",
        describe_operation="DescribeTrainingJob",
        name_field="TrainingJobName",
        primary_keys=("training_job_arn",),
    ),
    "processing_jobs": SageMakerEndpoint(
        list_operation="ListProcessingJobs",
        result_key="ProcessingJobSummaries",
        describe_operation="DescribeProcessingJob",
        name_field="ProcessingJobName",
        primary_keys=("processing_job_arn",),
    ),
    "endpoints": SageMakerEndpoint(
        list_operation="ListEndpoints",
        result_key="Endpoints",
        describe_operation="DescribeEndpoint",
        name_field="EndpointName",
        primary_keys=("endpoint_arn",),
    ),
    "models": SageMakerEndpoint(
        list_operation="ListModels",
        result_key="Models",
        describe_operation="DescribeModel",
        name_field="ModelName",
        primary_keys=("model_arn",),
        incremental=True,
    ),
    "endpoint_configs": SageMakerEndpoint(
        list_operation="ListEndpointConfigs",
        result_key="EndpointConfigs",
        describe_operation="DescribeEndpointConfig",
        name_field="EndpointConfigName",
        primary_keys=("endpoint_config_arn",),
        incremental=True,
    ),
    "model_packages": SageMakerEndpoint(
        list_operation="ListModelPackages",
        result_key="ModelPackageSummaryList",
        describe_operation="DescribeModelPackage",
        name_field="ModelPackageName",
        primary_keys=("model_package_arn",),
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
        primary_keys=("hyper_parameter_tuning_job_arn",),
    ),
    "automl_jobs": SageMakerEndpoint(
        list_operation="ListAutoMLJobs",
        result_key="AutoMLJobSummaries",
        describe_operation="DescribeAutoMLJobV2",
        name_field="AutoMLJobName",
        primary_keys=("auto_ml_job_arn",),
    ),
    "transform_jobs": SageMakerEndpoint(
        list_operation="ListTransformJobs",
        result_key="TransformJobSummaries",
        describe_operation="DescribeTransformJob",
        name_field="TransformJobName",
        primary_keys=("transform_job_arn",),
    ),
    "pipeline_executions": SageMakerEndpoint(
        list_operation="ListPipelineExecutions",
        result_key="PipelineExecutionSummaries",
        describe_operation="DescribePipelineExecution",
        name_field="PipelineExecutionArn",
        primary_keys=("pipeline_execution_arn",),
        parent=SageMakerParent(
            list_operation="ListPipelines",
            result_key="PipelineSummaries",
            name_field="PipelineName",
        ),
    ),
    "experiments": SageMakerEndpoint(
        list_operation="ListExperiments",
        result_key="ExperimentSummaries",
        describe_operation="DescribeExperiment",
        name_field="ExperimentName",
        primary_keys=("experiment_arn",),
    ),
    "trials": SageMakerEndpoint(
        list_operation="ListTrials",
        result_key="TrialSummaries",
        describe_operation="DescribeTrial",
        name_field="TrialName",
        primary_keys=("trial_arn",),
    ),
    "trial_components": SageMakerEndpoint(
        list_operation="ListTrialComponents",
        result_key="TrialComponentSummaries",
        describe_operation="DescribeTrialComponent",
        name_field="TrialComponentName",
        primary_keys=("trial_component_arn",),
    ),
    "monitoring_executions": SageMakerEndpoint(
        list_operation="ListMonitoringExecutions",
        result_key="MonitoringExecutionSummaries",
        # Executions have no ARN, and a schedule runs at most once per scheduled time.
        primary_keys=("monitoring_schedule_name", "scheduled_time"),
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
    "transform_jobs": "Batch transform jobs with status, model, input and output settings, and run times.",
    "pipeline_executions": "Pipeline executions with status, failure reason, and run times for every pipeline.",
    "experiments": "Experiments with source, display name, and creation details.",
    "trials": "Experiment trials with their experiment, source, and metadata.",
    "trial_components": "Trial components with status, parameters, artifacts, and metric summaries.",
    "monitoring_executions": "Model monitoring executions with status, schedule, endpoint, and failure reason.",
}
