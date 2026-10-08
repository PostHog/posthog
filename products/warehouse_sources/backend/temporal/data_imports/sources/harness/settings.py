from typing import Literal

from posthog.dataclasses import frozen

REGIONS = {
    "us": "https://app.harness.io",
    "us3": "https://app3.harness.io",
    "us_accounts": "https://accounts.harness.io",
    "eu": "https://accounts.eu.harness.io",
}

AUTH_ERROR = "Harness rejected your API key. Create a new token and reconnect."
PERMISSION_ERROR = "Your Harness token needs view permission for this table in the selected project."
REGION_ERROR = "Select a supported Harness region."


@frozen
class HarnessEndpoint:
    path: str
    primary_key: str = "identifier"
    method: Literal["GET", "POST"] = "GET"
    filter_type: str | None = None
    wrapper: str | None = None


ENDPOINTS = {
    "pipelines": HarnessEndpoint(path="/pipeline/api/pipelines/list", method="POST", filter_type="PipelineSetup"),
    "executions": HarnessEndpoint(
        path="/pipeline/api/pipelines/execution/summary",
        primary_key="planExecutionId",
        method="POST",
        filter_type="PipelineExecution",
    ),
    "services": HarnessEndpoint(path="/ng/api/servicesV2", wrapper="service"),
    "environments": HarnessEndpoint(path="/ng/api/environmentsV2", wrapper="environment"),
}
