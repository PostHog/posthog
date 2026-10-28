from posthog.dataclasses import frozen

API_VERSION = "2016-11-23"
TARGET_PREFIXES = {API_VERSION: "AWSStepFunctions"}
CONTENT_TYPE = "application/x-amz-json-1.0"
PAGE_SIZE = 100
# Parents a permission probe checks for a child before it accepts the credentials.
PROBE_PARENT_LIMIT = 20


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
    "state_machine_versions": StepFunctionsEndpoint(
        operation="ListStateMachineVersions",
        result_key="stateMachineVersions",
        primary_keys=("state_machine_version_arn",),
    ),
    "state_machine_aliases": StepFunctionsEndpoint(
        operation="ListStateMachineAliases",
        result_key="stateMachineAliases",
        primary_keys=("state_machine_alias_arn",),
    ),
    "activities": StepFunctionsEndpoint(
        operation="ListActivities", result_key="activities", primary_keys=("activity_arn",)
    ),
    "map_runs": StepFunctionsEndpoint(operation="ListMapRuns", result_key="mapRuns", primary_keys=("map_run_arn",)),
    "map_run_executions": StepFunctionsEndpoint(
        operation="ListExecutions", result_key="executions", primary_keys=("execution_arn",)
    ),
}
MACHINE_CHILD_ENDPOINTS = frozenset({"state_machine_versions", "state_machine_aliases"})
MAP_RUN_ENDPOINTS = frozenset({"map_runs", "map_run_executions"})
ENDPOINT_DESCRIPTIONS = {
    "state_machines": "State machines in the configured AWS region, including Standard and Express workflows.",
    "executions": "Execution status and times for Standard workflows in the configured AWS region.",
    "execution_history": "History events for Standard workflow executions, without input or output payloads.",
    "state_machine_versions": "Published versions of each state machine in the configured AWS region.",
    "state_machine_aliases": "Aliases of each state machine, with the versions they route executions to.",
    "activities": "Activities that workers poll for tasks in the configured AWS region.",
    "map_runs": "Distributed Map runs started by Standard workflow executions, with item and child execution counts.",
    "map_run_executions": "Child workflow executions started by each Distributed Map run.",
}
PERMISSION_MESSAGE = (
    "Grant states:ListStateMachines, states:ListExecutions, states:GetExecutionHistory, "
    "states:ListStateMachineVersions, states:ListStateMachineAliases, states:DescribeStateMachineAlias, "
    "states:ListActivities, states:ListMapRuns, and states:DescribeMapRun for the tables you select."
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
