from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BATCH_API_VERSION = "2016-08-10"
PAGE_SIZE = 100


@frozen
class AwsBatchEndpoint:
    operation: str
    result_key: str
    primary_key: str
    description: str


AWS_BATCH_ENDPOINTS: dict[str, AwsBatchEndpoint] = {
    "jobs": AwsBatchEndpoint(
        operation="ListJobs",
        result_key="jobSummaryList",
        primary_key="job_arn",
        description="Jobs in each queue, with their status, attempts, and execution details. Array children and nodes are in the job_children table.",
    ),
    "job_children": AwsBatchEndpoint(
        operation="DescribeJobs",
        result_key="jobs",
        primary_key="job_arn",
        description="Child jobs of array jobs and nodes of multi-node parallel jobs, with their execution details.",
    ),
    "service_jobs": AwsBatchEndpoint(
        operation="ListServiceJobs",
        result_key="jobSummaryList",
        primary_key="job_arn",
        description="Service jobs, such as SageMaker training jobs, in each service job queue.",
    ),
    "job_queues": AwsBatchEndpoint(
        operation="DescribeJobQueues",
        result_key="jobQueues",
        primary_key="job_queue_arn",
        description="Job queues, their priorities, and their associated compute environments.",
    ),
    "compute_environments": AwsBatchEndpoint(
        operation="DescribeComputeEnvironments",
        result_key="computeEnvironments",
        primary_key="compute_environment_arn",
        description="Compute environments, their capacity settings, and their state.",
    ),
    "job_definitions": AwsBatchEndpoint(
        operation="DescribeJobDefinitions",
        result_key="jobDefinitions",
        primary_key="job_definition_arn",
        description="Job definition revisions, including their resource requirements and container settings.",
    ),
    "scheduling_policies": AwsBatchEndpoint(
        operation="ListSchedulingPolicies",
        result_key="schedulingPolicies",
        primary_key="arn",
        description="Scheduling policies and their fair-share settings.",
    ),
    "consumable_resources": AwsBatchEndpoint(
        operation="ListConsumableResources",
        result_key="consumableResources",
        primary_key="consumable_resource_arn",
        description="Consumable resources with their total, in-use, and available quantities.",
    ),
}
ENDPOINTS = tuple(AWS_BATCH_ENDPOINTS)
ENDPOINT_DESCRIPTIONS = {name: endpoint.description for name, endpoint in AWS_BATCH_ENDPOINTS.items()}

# A creation filter misses later job status changes. Full refresh keeps those changes visible.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

PERMISSION_MESSAGE = (
    "AWS denied access to Batch. Grant batch:DescribeJobQueues, batch:ListJobs, batch:DescribeJobs, "
    "batch:ListServiceJobs, batch:DescribeComputeEnvironments, batch:DescribeJobDefinitions, "
    "batch:ListSchedulingPolicies, batch:DescribeSchedulingPolicies, batch:ListConsumableResources, "
    "and batch:DescribeConsumableResource for the tables you select."
)
CREDENTIAL_MESSAGE = "AWS rejected the credentials. Check the access key ID, secret access key, and session token."
NON_RETRYABLE_ERRORS: dict[str, str] = {
    **dict.fromkeys(
        ("UnrecognizedClientException", "InvalidClientTokenId", "SignatureDoesNotMatch", "InvalidSignatureException"),
        CREDENTIAL_MESSAGE,
    ),
    "ExpiredToken": "The AWS session token has expired. Enter new credentials.",
    "AccessDenied": PERMISSION_MESSAGE,
    "not authorized to perform": PERMISSION_MESSAGE,
    "SubscriptionRequiredException": "Enable AWS Batch for this account before you connect it.",
    "OptInRequired": "Enable AWS Batch in the selected region before you connect it.",
    "not subscribed": "Enable AWS Batch for this account before you connect it.",
}
