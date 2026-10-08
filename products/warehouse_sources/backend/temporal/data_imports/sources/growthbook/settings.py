from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

DEFAULT_BASE_URL = "https://api.growthbook.io/api"
PAGE_SIZE = 100


@frozen
class GrowthBookEndpoint:
    path: str
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "dateCreated"
    paginated: bool = True
    params: dict[str, str] = field(default_factory=dict)


# GrowthBook only exposes v2 for features; the other entities retain their v1 routes.
ENDPOINTS: dict[str, GrowthBookEndpoint] = {
    "features": GrowthBookEndpoint(
        path="{api_version}/features", data_selector="features", params={"archived": "true"}
    ),
    "experiments": GrowthBookEndpoint(path="v1/experiments", data_selector="experiments"),
    "metrics": GrowthBookEndpoint(path="v1/metrics", data_selector="metrics", params={"includeArchived": "true"}),
    "fact_tables": GrowthBookEndpoint(path="v1/fact-tables", data_selector="factTables"),
    "fact_metrics": GrowthBookEndpoint(path="v1/fact-metrics", data_selector="factMetrics"),
    "segments": GrowthBookEndpoint(path="v1/segments", data_selector="segments"),
    "dimensions": GrowthBookEndpoint(path="v1/dimensions", data_selector="dimensions"),
    "projects": GrowthBookEndpoint(path="v1/projects", data_selector="projects"),
    "environments": GrowthBookEndpoint(
        path="v1/environments", data_selector="environments", partition_key=None, paginated=False
    ),
    "saved_groups": GrowthBookEndpoint(path="v1/saved-groups", data_selector="savedGroups"),
    "data_sources": GrowthBookEndpoint(path="v1/data-sources", data_selector="dataSources"),
    "members": GrowthBookEndpoint(path="v1/members", data_selector="members", partition_key=None),
}

# Timestamp fields in responses do not imply server-side timestamp filtering.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
