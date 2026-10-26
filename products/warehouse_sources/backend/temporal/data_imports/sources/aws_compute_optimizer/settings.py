from posthog.dataclasses import frozen

API_VERSION = "2019-11-01"
API_DOCS_URL = "https://docs.aws.amazon.com/compute-optimizer/latest/APIReference/"
TARGET_PREFIXES = {API_VERSION: "ComputeOptimizerService"}
DEFAULT_REGION = "us-east-1"
PAGE_SIZE = 100
# One daily peak per metric keeps the fan-out tables small while matching how Compute Optimizer sizes resources.
PROJECTED_METRICS_STAT = "Maximum"
PROJECTED_METRICS_PERIOD_SECONDS = 86400
DEFAULT_LOOKBACK_DAYS = 14


@frozen
class ProjectedMetricsFanout:
    parent: str
    arn_field: str
    lookback_field: str


@frozen
class Endpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    description: str
    fanout: ProjectedMetricsFanout | None = None


ENDPOINTS: dict[str, Endpoint] = {
    "ec2_instance_recommendations": Endpoint(
        operation="GetEC2InstanceRecommendations",
        result_key="instanceRecommendations",
        primary_keys=("instance_arn",),
        description="EC2 instance recommendations with utilization metrics and estimated savings.",
    ),
    "auto_scaling_group_recommendations": Endpoint(
        operation="GetAutoScalingGroupRecommendations",
        result_key="autoScalingGroupRecommendations",
        primary_keys=("auto_scaling_group_arn",),
        description="Auto Scaling group recommendations with configuration options and estimated savings.",
    ),
    "lambda_function_recommendations": Endpoint(
        operation="GetLambdaFunctionRecommendations",
        result_key="lambdaFunctionRecommendations",
        primary_keys=("function_arn", "function_version"),
        description="Lambda function recommendations with memory options and estimated savings.",
    ),
    "ecs_service_recommendations": Endpoint(
        operation="GetECSServiceRecommendations",
        result_key="ecsServiceRecommendations",
        primary_keys=("service_arn",),
        description="ECS service recommendations with CPU, memory, and estimated savings.",
    ),
    "ebs_volume_recommendations": Endpoint(
        operation="GetEBSVolumeRecommendations",
        result_key="volumeRecommendations",
        primary_keys=("volume_arn",),
        description="EBS volume recommendations with configuration options and estimated savings.",
    ),
    "rds_database_recommendations": Endpoint(
        operation="GetRDSDatabaseRecommendations",
        result_key="rdsDBRecommendations",
        primary_keys=("resource_arn",),
        description="Aurora and RDS database recommendations for instance classes and storage, with estimated savings.",
    ),
    "idle_recommendations": Endpoint(
        operation="GetIdleRecommendations",
        result_key="idleRecommendations",
        primary_keys=("resource_arn",),
        description="Idle resources across resource types, with utilization metrics and estimated savings.",
    ),
    "ec2_recommendation_projected_metrics": Endpoint(
        operation="GetEC2RecommendationProjectedMetrics",
        result_key="recommendedOptionProjectedMetrics",
        primary_keys=("instance_arn", "rank", "metric_name", "timestamp"),
        description="Daily peak CPU and memory utilization projected for each recommended EC2 instance type.",
        fanout=ProjectedMetricsFanout(
            parent="ec2_instance_recommendations", arn_field="instanceArn", lookback_field="lookBackPeriodInDays"
        ),
    ),
    "ecs_service_recommendation_projected_metrics": Endpoint(
        operation="GetECSServiceRecommendationProjectedMetrics",
        result_key="recommendedOptionProjectedMetrics",
        primary_keys=("service_arn", "recommended_cpu_units", "recommended_memory_size", "metric_name", "timestamp"),
        description="Daily peak CPU and memory utilization bounds projected for each recommended ECS service size.",
        fanout=ProjectedMetricsFanout(
            parent="ecs_service_recommendations", arn_field="serviceArn", lookback_field="lookbackPeriodInDays"
        ),
    ),
    "recommendation_summaries": Endpoint(
        operation="GetRecommendationSummaries",
        result_key="recommendationSummaries",
        primary_keys=("account_id", "recommendation_resource_type", "region"),
        description="Counts of optimization findings and estimated savings by account and resource type.",
    ),
}

ERROR_MESSAGES = {
    "AccessDeniedException": "AWS denied access. Grant the compute-optimizer read permission for the selected table.",
    "AccessDenied": "AWS denied access. Grant the compute-optimizer read permission for the selected table.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredTokenException": "The AWS session token expired. Reconnect with new credentials.",
    "ExpiredToken": "The AWS session token expired. Reconnect with new credentials.",
    "MissingAuthenticationToken": "AWS requires credentials. Enter an access key ID and secret access key.",
    "OptInRequiredException": "Enable AWS Compute Optimizer for this account before you sync recommendations.",
    "SubscriptionRequiredException": "Enable AWS Compute Optimizer for this account before you sync recommendations.",
}
