from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

PAGE_SIZE = 100
# Fetch endpoints count `limit` in traces, so one page can hold many more rows than this.
EVENTS_PAGE_SIZE = 100
# Virtual-hosted S3 bucket hosts, global or regional (`<bucket>.s3.<region>.amazonaws.com`).
S3_HOST_PATTERN = r"[a-z0-9][a-z0-9.-]*\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com"


@frozen
class BraintrustEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = None
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


def _events_endpoint(name: str, path: str, parent_name: str, parent_key: str) -> BraintrustEndpoint:
    return BraintrustEndpoint(
        name=name,
        path=path,
        primary_keys=(parent_key, "id"),
        partition_key="created",
        page_size=EVENTS_PAGE_SIZE,
        fanout=DependentEndpointConfig(
            parent_name=parent_name,
            resolve_param=parent_key,
            resolve_field="id",
            include_from_parent=[],
            parent_params={"limit": PAGE_SIZE},
        ),
    )


ENDPOINTS: dict[str, BraintrustEndpoint] = {
    "projects": BraintrustEndpoint(name="projects", path="v1/project"),
    "experiments": BraintrustEndpoint(name="experiments", path="v1/experiment"),
    "datasets": BraintrustEndpoint(name="datasets", path="v1/dataset"),
    "prompts": BraintrustEndpoint(name="prompts", path="v1/prompt"),
    "functions": BraintrustEndpoint(name="functions", path="v1/function"),
    "users": BraintrustEndpoint(name="users", path="v1/user"),
    "project_logs": _events_endpoint(
        "project_logs", "v1/project_logs/{project_id}/fetch", parent_name="projects", parent_key="project_id"
    ),
    "experiment_events": _events_endpoint(
        "experiment_events",
        "v1/experiment/{experiment_id}/fetch",
        parent_name="experiments",
        parent_key="experiment_id",
    ),
    "dataset_events": _events_endpoint(
        "dataset_events", "v1/dataset/{dataset_id}/fetch", parent_name="datasets", parent_key="dataset_id"
    ),
}

AUTH_ERRORS = {
    401: "Braintrust rejected the API key. Check the key in your organization settings.",
    403: "The Braintrust API key cannot read this resource. Check its permissions and the API URL.",
}
