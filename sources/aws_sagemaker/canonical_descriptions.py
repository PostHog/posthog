from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "training_jobs": {
        "description": "SageMaker training jobs, including their status, resource configuration, and final metrics.",
        "docs_url": "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeTrainingJob.html",
        "columns": {
            "training_job_arn": "The Amazon Resource Name of the training job.",
            "training_job_name": "The name of the training job.",
            "training_job_status": "The status of the training job.",
            "creation_time": "The time AWS created the training job.",
            "last_modified_time": "The time AWS last modified the training job.",
            "training_start_time": "The time training started.",
            "training_end_time": "The time training ended.",
            "training_time_in_seconds": "The duration of model training, in seconds.",
            "billable_time_in_seconds": "The training duration used for billing, in seconds.",
            "resource_config": "The compute instances and storage configured for training.",
            "final_metric_data_list": "The final values of metrics from the training job.",
        },
    },
    "processing_jobs": {
        "description": "SageMaker processing jobs, including their status, compute resources, and input and output settings.",
        "docs_url": "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeProcessingJob.html",
        "columns": {
            "processing_job_arn": "The Amazon Resource Name of the processing job.",
            "processing_job_name": "The name of the processing job.",
            "processing_job_status": "The status of the processing job.",
            "creation_time": "The time AWS created the processing job.",
            "last_modified_time": "The time AWS last modified the processing job.",
            "processing_start_time": "The time processing started.",
            "processing_end_time": "The time processing ended.",
            "processing_resources": "The compute resources configured for processing.",
            "failure_reason": "The reason the processing job failed.",
        },
    },
    "endpoints": {
        "description": "SageMaker inference endpoints, including their status and deployed production variants.",
        "docs_url": "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeEndpoint.html",
        "columns": {
            "endpoint_arn": "The Amazon Resource Name of the endpoint.",
            "endpoint_name": "The name of the endpoint.",
            "endpoint_config_name": "The endpoint configuration used for deployment.",
            "endpoint_status": "The status of the endpoint.",
            "creation_time": "The time AWS created the endpoint.",
            "last_modified_time": "The time AWS last modified the endpoint.",
            "production_variants": "The production variants deployed on the endpoint, including instance counts and weights.",
        },
    },
    "models": {
        "description": "SageMaker models, including container definitions, execution roles, and network settings.",
        "docs_url": "https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeModel.html",
        "columns": {
            "model_arn": "The Amazon Resource Name of the model.",
            "model_name": "The name of the model.",
            "creation_time": "The time AWS created the model.",
            "primary_container": "The primary container used for inference.",
            "containers": "The containers in the inference pipeline.",
            "execution_role_arn": "The IAM role SageMaker uses to access AWS resources for the model.",
            "vpc_config": "The VPC subnets and security groups used by the model.",
        },
    },
}
