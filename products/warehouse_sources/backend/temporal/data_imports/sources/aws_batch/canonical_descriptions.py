from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "jobs": {
        "description": "AWS Batch jobs in the selected region, with execution details and attempts.",
        "docs_url": "https://docs.aws.amazon.com/batch/latest/APIReference/API_DescribeJobs.html",
        "columns": {
            "job_arn": "ARN that identifies the job across accounts and regions.",
            "job_id": "Identifier assigned to the job by AWS Batch.",
            "job_name": "Name supplied when the job was submitted.",
            "job_queue": "ARN of the queue to which the job was submitted.",
            "job_definition": "Job definition revision used to start the job.",
            "status": "Current state of the job, such as RUNNING, SUCCEEDED, or FAILED.",
            "status_reason": "Reason for the current job state.",
            "created_at": "Time when the job was created, converted from milliseconds to a UTC timestamp.",
            "started_at": "Time when the job started, converted to UTC. Null if the job has not started.",
            "stopped_at": "Time when the job stopped, converted to UTC. Null if the job has not stopped.",
            "attempts": "Execution attempts, including timing, container details, and failure reasons.",
            "container": "Container configuration and execution details returned for the job.",
            "region": "AWS region selected for this source.",
        },
    },
    "job_queues": {
        "description": "Queues that accept AWS Batch jobs and assign them to compute environments.",
        "docs_url": "https://docs.aws.amazon.com/batch/latest/APIReference/API_DescribeJobQueues.html",
        "columns": {
            "job_queue_arn": "ARN that identifies the queue across accounts and regions.",
            "job_queue_name": "Name of the job queue.",
            "state": "Whether the queue accepts new jobs.",
            "status": "Current status of the queue.",
            "priority": "Scheduling priority relative to queues that share a compute environment.",
            "compute_environment_order": "Compute environments associated with the queue and their selection order.",
            "scheduling_policy_arn": "ARN of the scheduling policy associated with the queue.",
            "region": "AWS region selected for this source.",
        },
    },
    "compute_environments": {
        "description": "AWS Batch compute environments and their capacity configuration.",
        "docs_url": "https://docs.aws.amazon.com/batch/latest/APIReference/API_DescribeComputeEnvironments.html",
        "columns": {
            "compute_environment_arn": "ARN that identifies the compute environment across accounts and regions.",
            "compute_environment_name": "Name of the compute environment.",
            "type": "Whether AWS Batch manages the compute environment.",
            "state": "Whether the compute environment accepts jobs.",
            "status": "Current status of the compute environment.",
            "compute_resources": "Capacity, instance, and network settings for managed compute resources.",
            "ecs_cluster_arn": "ARN of the associated Amazon ECS cluster.",
            "region": "AWS region selected for this source.",
        },
    },
    "job_definitions": {
        "description": "AWS Batch job definition revisions and their execution configuration.",
        "docs_url": "https://docs.aws.amazon.com/batch/latest/APIReference/API_DescribeJobDefinitions.html",
        "columns": {
            "job_definition_arn": "ARN that identifies a specific job definition revision.",
            "job_definition_name": "Name shared by revisions of this job definition.",
            "revision": "Revision number of the job definition.",
            "status": "Whether the revision is ACTIVE or INACTIVE.",
            "type": "Job definition type, such as container or multinode.",
            "container_properties": "Container settings, including the image, command, and resource requirements.",
            "retry_strategy": "Rules that control retries after a job fails.",
            "region": "AWS region selected for this source.",
        },
    },
}
