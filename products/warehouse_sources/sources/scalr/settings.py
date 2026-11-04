from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen


@frozen
class ScalrEndpoint:
    path: str
    sort: str | None = None
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    account_filter: bool = True
    include: str | None = None
    per_workspace: bool = False


ENDPOINTS = {
    "environments": ScalrEndpoint(path="environments", sort="created-at"),
    "workspaces": ScalrEndpoint(path="workspaces", sort="updated-at"),
    # A creation filter would miss later run status changes, so runs require full refresh.
    "runs": ScalrEndpoint(path="runs"),
    "users": ScalrEndpoint(path="users", sort="created-at", account_filter=False),
    # Plans have only a by-ID route, so read them as included resources of the run list.
    "plans": ScalrEndpoint(path="runs", include="plan", partition_key=None),
    # The route requires a workspace filter, so it fans out over workspaces.
    "state_versions": ScalrEndpoint(path="state-versions", sort="created-at", account_filter=False, per_workspace=True),
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
