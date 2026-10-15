from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

PAGE_SIZE = 100


@frozen
class LookerEndpoint:
    path: str
    primary_key: str = "id"
    partition_key: str | None = None
    paginated: bool = True
    sorts: str | None = "id"
    fields: str | None = None
    active_only: bool = False


# The API exposes no creation or update filter for these tables. Account behavior remains unverified.
ENDPOINTS: dict[str, LookerEndpoint] = {
    "users": LookerEndpoint(
        path="users",
        # Credential and session objects do not belong in the imported user table.
        fields="id,first_name,last_name,display_name,email,is_disabled,group_ids,role_ids,home_folder_id,personal_folder_id,locale",
    ),
    "looks": LookerEndpoint(path="looks/search", partition_key="created_at", active_only=True),
    "dashboards": LookerEndpoint(path="dashboards/search", partition_key="created_at", active_only=True),
    "projects": LookerEndpoint(path="projects", paginated=False, sorts=None),
    "folders": LookerEndpoint(path="folders/search", partition_key="created_at"),
    # Models accept offsets without a sort parameter; concurrent changes can move page boundaries.
    "lookml_models": LookerEndpoint(path="lookml_models", primary_key="name", sorts=None),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
