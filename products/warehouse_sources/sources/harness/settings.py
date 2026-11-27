from typing import Literal

from products.warehouse_sources.sources.sdk import frozen

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
    column: str
    field: str = "identifier"
    # Without a param, the path binds the parent field at `{parent_identifier}`.
    param: str | None = None
    # Query params bound from other parent fields, as (param, parent field) pairs.
    extra: tuple[tuple[str, str], ...] = ()


@frozen
class HarnessEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("identifier",)
    method: Literal["GET", "POST"] = "GET"
    filter_type: str | None = None
    wrapper: str | None = None
    # `v1` endpoints take the organization and project in the path and the account in a header.
    scope: Literal["account", "project", "v1"] = "project"
    page_param: str = "page"
    size_param: str = "size"
    paginated: bool = True
    data_selector: str = "data.content"
    parent: HarnessParent | None = None
    # Drops rows whose field is empty, for endpoints that answer every parent with one object.
    require_field: str | None = None


EXECUTION_PARENT = HarnessParent(name="executions", column="planExecutionId", field="planExecutionId")

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
        parent=HarnessParent(name="environments", column="environmentRef", param="environmentIdentifier"),
    ),
    "user_groups": HarnessEndpoint(
        path="/ng/api/user-groups",
        page_param="pageIndex",
        size_param="pageSize",
    ),
    "approval_instances": HarnessEndpoint(
        path="/v1/orgs/{org}/projects/{project}/approvals/execution/{parent_identifier}",
        primary_keys=("planExecutionId", "id"),
        scope="v1",
        paginated=False,
        data_selector="$",
        parent=EXECUTION_PARENT,
    ),
    "execution_notes": HarnessEndpoint(
        path="/pipeline/api/pipelines/execution/{parent_identifier}/notes",
        primary_keys=("planExecutionId",),
        scope="account",
        paginated=False,
        data_selector="data",
        parent=EXECUTION_PARENT,
        require_field="notes",
    ),
    "execution_annotations": HarnessEndpoint(
        path="/pipeline/api/pipelines/execution/{parent_identifier}/annotations",
        primary_keys=("planExecutionId", "contextId"),
        paginated=False,
        data_selector="data.annotations",
        parent=HarnessParent(
            name="executions",
            column="planExecutionId",
            field="planExecutionId",
            extra=(("pipelineIdentifier", "pipelineIdentifier"),),
        ),
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
