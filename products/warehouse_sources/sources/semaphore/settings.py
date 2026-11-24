from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen, incremental_field


@frozen
class SemaphoreEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    data_selector: str | None = None
    project_param: bool = True
    paginator: Literal["header_link", "page_number", "deployment_history"] = "header_link"
    sort_mode: Literal["desc"] | None = "desc"
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    # Read only by the shared fan-out helper; these requests send no page size.
    page_size: int = 0


ENDPOINTS = {
    "workflows": SemaphoreEndpoint(name="workflows", path="plumber-workflows", primary_keys=("wf_id",)),
    "pipelines": SemaphoreEndpoint(name="pipelines", path="pipelines", primary_keys=("ppl_id",)),
    "deployment_targets": SemaphoreEndpoint(name="deployment_targets", path="deployment_targets", primary_keys=("id",)),
    "members": SemaphoreEndpoint(
        name="members",
        path="members",
        primary_keys=("id",),
        data_selector="members",
        project_param=False,
        paginator="page_number",
        sort_mode=None,
    ),
    "deployment_history": SemaphoreEndpoint(
        name="deployment_history",
        path="deployment_targets/{target_id}/history",
        primary_keys=("target_id", "id"),
        data_selector="deployments",
        project_param=False,
        paginator="deployment_history",
        sort_mode=None,
        fanout=DependentEndpointConfig(
            parent_name="deployment_targets",
            resolve_param="target_id",
            resolve_field="id",
            include_from_parent=[],
        ),
    ),
    "flaky_tests": SemaphoreEndpoint(
        name="flaky_tests",
        path="projects/{project_id}/test_results/flaky_tests",
        primary_keys=("id",),
        project_param=False,
        sort_mode=None,
    ),
    "flaky_test_disruptions": SemaphoreEndpoint(
        name="flaky_test_disruptions",
        path="projects/{project_id}/test_results/flaky_tests/{flaky_test_id}/disruptions",
        primary_keys=("flaky_test_id", "pipeline_id", "created_at"),
        project_param=False,
        sort_mode=None,
        fanout=DependentEndpointConfig(
            parent_name="flaky_tests",
            resolve_param="flaky_test_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "flaky_test_id"},
        ),
    ),
}

INCREMENTAL_FIELDS = {"workflows": [incremental_field("created_at")]}
API_DOCS_URL = "https://docs.semaphore.io/reference/api"
AUTH_ERROR = "Semaphore rejected your API token. Check the token in your account settings."
PERMISSION_ERROR = "Your Semaphore token cannot read this project. Check your project permissions."
NOT_FOUND_ERROR = (
    "Semaphore could not find this project. Check the organization name, project ID, and token permissions."
)
