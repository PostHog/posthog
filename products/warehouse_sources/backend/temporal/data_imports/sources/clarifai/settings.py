from dataclasses import field
from typing import Any

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)

DEFAULT_API_HOST = "https://api.clarifai.com"
PAGE_SIZE = 128


@frozen
class ClarifaiEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    params: dict[str, Any] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None
    page_size: int = PAGE_SIZE
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: str | None = None


CLARIFAI_ENDPOINTS: dict[str, ClarifaiEndpointConfig] = {
    endpoint.name: endpoint
    for endpoint in (
        ClarifaiEndpointConfig(name="models", path="models", data_selector="models"),
        ClarifaiEndpointConfig(name="workflows", path="workflows", data_selector="workflows"),
        ClarifaiEndpointConfig(name="datasets", path="datasets", data_selector="datasets"),
        ClarifaiEndpointConfig(name="concepts", path="concepts", data_selector="concepts"),
        ClarifaiEndpointConfig(name="inputs", path="inputs", data_selector="inputs"),
        # Without a concept ID in the path, ListConceptRelations returns every relation in the app.
        ClarifaiEndpointConfig(name="concept_relations", path="concepts/relations", data_selector="concept_relations"),
        # Without this flag the API returns only trusted annotations, which hides pending and rejected reviews.
        ClarifaiEndpointConfig(
            name="annotations",
            path="annotations",
            data_selector="annotations",
            params={"list_all_annotations": "true"},
        ),
        # Without this flag the API leaves out failed evaluation runs.
        ClarifaiEndpointConfig(
            name="evaluations",
            path="evaluations",
            data_selector="eval_metrics",
            params={"show_failed_metrics": "true"},
        ),
        # Without this flag the API leaves out label order tasks.
        ClarifaiEndpointConfig(
            name="tasks",
            path="tasks",
            data_selector="tasks",
            params={"including_label_order_tasks": "true"},
        ),
        # Without this flag the API leaves out deleted collaborators, which hides past access.
        ClarifaiEndpointConfig(
            name="collaborators",
            path="collaborators",
            data_selector="collaborators",
            params={"list_all_collaborators": "true"},
        ),
        # Dataset inputs carry no ID of their own, so the key combines the dataset ID and the input ID.
        ClarifaiEndpointConfig(
            name="dataset_inputs",
            path="datasets/{dataset_id}/inputs",
            data_selector="dataset_inputs",
            primary_keys=["dataset_id", "input_id"],
            fanout=DependentEndpointConfig(
                parent_name="datasets",
                resolve_param="dataset_id",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "dataset_id"},
            ),
        ),
        ClarifaiEndpointConfig(
            name="model_versions",
            path="models/{model_id}/versions",
            data_selector="model_versions",
            primary_keys=["model_id", "id"],
            fanout=DependentEndpointConfig(
                parent_name="models",
                resolve_param="model_id",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "model_id"},
            ),
        ),
        ClarifaiEndpointConfig(
            name="dataset_versions",
            path="datasets/{dataset_id}/versions",
            data_selector="dataset_versions",
            primary_keys=["dataset_id", "id"],
            fanout=DependentEndpointConfig(
                parent_name="datasets",
                resolve_param="dataset_id",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "dataset_id"},
            ),
        ),
        ClarifaiEndpointConfig(
            name="workflow_versions",
            path="workflows/{workflow_id}/versions",
            data_selector="workflow_versions",
            primary_keys=["workflow_id", "id"],
            fanout=DependentEndpointConfig(
                parent_name="workflows",
                resolve_param="workflow_id",
                resolve_field="id",
                include_from_parent=["id"],
                parent_field_renames={"id": "workflow_id"},
            ),
        ),
    )
}
ENDPOINTS = tuple(CLARIFAI_ENDPOINTS)

AUTH_ERROR = "Clarifai rejected the token. Check your personal access token and app access."
PERMISSION_ERROR = (
    "The Clarifai token lacks permission. Grant read access to the selected resource and its list endpoint."
)
HOST_ERROR = "Enter a public HTTPS API host without a path, query, or credentials."
RESOURCE_ERROR = "Clarifai could not find the resource. Check the user ID and app ID."
