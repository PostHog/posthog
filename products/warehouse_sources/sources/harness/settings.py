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
class HarnessParent:
    name: str
    param: str
    column: str


@frozen
class HarnessEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("identifier",)
    method: Literal["GET", "POST"] = "GET"
    filter_type: str | None = None
    wrapper: str | None = None
    scope: Literal["account", "project"] = "project"
    page_param: str = "page"
    size_param: str = "size"
    parent: HarnessParent | None = None


ENDPOINTS = {
    "pipelines": HarnessEndpoint(path="/pipeline/api/pipelines/list", method="POST", filter_type="PipelineSetup"),
    "executions": HarnessEndpoint(
        path="/pipeline/api/pipelines/execution/summary",
        primary_keys=("planExecutionId",),
        method="POST",
        filter_type="PipelineExecution",
    ),
    "services": HarnessEndpoint(path="/ng/api/servicesV2", wrapper="service"),
    "environments": HarnessEndpoint(path="/ng/api/environmentsV2", wrapper="environment"),
    # Harness requires an environment for this list, so it fans out over the environments list.
    "infrastructures": HarnessEndpoint(
        path="/ng/api/infrastructures",
        primary_keys=("environmentRef", "identifier"),
        wrapper="infrastructure",
        parent=HarnessParent(name="environments", param="environmentIdentifier", column="environmentRef"),
    ),
    "organizations": HarnessEndpoint(
        path="/ng/api/organizations",
        wrapper="organization",
        scope="account",
        page_param="pageIndex",
        size_param="pageSize",
    ),
    "projects": HarnessEndpoint(
        path="/ng/api/projects",
        primary_keys=("orgIdentifier", "identifier"),
        wrapper="project",
        scope="account",
        page_param="pageIndex",
        size_param="pageSize",
    ),
}
