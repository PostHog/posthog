from posthog.dataclasses import frozen

API_VERSION = "2016-11-23"
TARGET_PREFIXES = {API_VERSION: "AWSStepFunctions"}
CONTENT_TYPE = "application/x-amz-json-1.0"
PAGE_SIZE = 100


@frozen
class StepFunctionsEndpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]


ENDPOINTS = {
    "state_machines": StepFunctionsEndpoint(
        operation="ListStateMachines", result_key="stateMachines", primary_keys=("state_machine_arn",)
    ),
    "executions": StepFunctionsEndpoint(
        operation="ListExecutions", result_key="executions", primary_keys=("execution_arn",)
    ),
    "execution_history": StepFunctionsEndpoint(
        operation="GetExecutionHistory", result_key="events", primary_keys=("execution_arn", "id")
    ),
}
ENDPOINT_DESCRIPTIONS = {
    "state_machines": "State machines in the configured AWS region, including Standard and Express workflows.",
    "executions": "Execution status and times for Standard workflows in the configured AWS region.",
    "execution_history": "History events for Standard workflow executions, without input or output payloads.",
}
PERMISSION_MESSAGE = (
    "Grant states:ListStateMachines, states:ListExecutions, and states:GetExecutionHistory for the tables you select."
)
ERROR_MESSAGES = {
    "AccessDenied": PERMISSION_MESSAGE,
    "AccessDeniedException": PERMISSION_MESSAGE,
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID, secret access key, and session token.",
    "InvalidClientTokenId": "AWS rejected the access key ID. Check that the key is active.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredTokenException": "The AWS session token expired. Connect again with current credentials.",
    "ExpiredToken": "The AWS session token expired. Connect again with current credentials.",
    "SubscriptionRequiredException": "Enable AWS Step Functions in this account and region, then try again.",
    "OptInRequired": "Enable AWS Step Functions in this account and region, then try again.",
    "KmsAccessDeniedException": "Grant access to the AWS KMS key used by this workflow.",
    "InvalidToken": "The AWS pagination token expired or is invalid. Restart the table sync.",
}
