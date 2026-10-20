from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class ScalrEndpoint:
    path: str
    sort: str | None = None
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "created_at"


ENDPOINTS = {
    "environments": ScalrEndpoint(path="environments", sort="created-at"),
    "workspaces": ScalrEndpoint(path="workspaces", sort="updated-at"),
    # A creation filter would miss later run status changes, so runs require full refresh.
    "runs": ScalrEndpoint(path="runs"),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "workspaces": [
        {
            "field": "updated_at",
            "label": "updated_at",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
}

AUTH_ERROR = "Scalr rejected the API token. Check that the token is valid and has read access to this account."
ACCESS_ERROR = "Scalr denied access. Check the account ID and the token permissions for the selected data."
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": ACCESS_ERROR,
    "404 Client Error": ACCESS_ERROR,
}
