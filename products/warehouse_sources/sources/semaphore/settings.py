from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field


@frozen
class SemaphoreEndpoint:
    path: str
    primary_key: str


ENDPOINTS = {
    "workflows": SemaphoreEndpoint(path="plumber-workflows", primary_key="wf_id"),
    "pipelines": SemaphoreEndpoint(path="pipelines", primary_key="ppl_id"),
    "deployment_targets": SemaphoreEndpoint(path="deployment_targets", primary_key="id"),
}

INCREMENTAL_FIELDS = {"workflows": [incremental_field("created_at")]}
API_DOCS_URL = "https://docs.semaphore.io/reference/api"
AUTH_ERROR = "Semaphore rejected your API token. Check the token in your account settings."
PERMISSION_ERROR = "Your Semaphore token cannot read this project. Check your project permissions."
NOT_FOUND_ERROR = (
    "Semaphore could not find this project. Check the organization name, project ID, and token permissions."
)
