from posthog.dataclasses import frozen

API_VERSION = "2019-11-01"
API_DOCS_URL = "https://docs.aws.amazon.com/compute-optimizer/latest/APIReference/"
TARGET_PREFIXES = {API_VERSION: "ComputeOptimizerService"}
DEFAULT_REGION = "us-east-1"
PAGE_SIZE = 100


@frozen
class Endpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    description: str


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
