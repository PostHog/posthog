from dataclasses import dataclass, field

LINGO_DEV_BASE_URL = "https://api.lingo.dev"


@dataclass
class LingoDevEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str = "createdAt"
    # Lingo.dev defaults to 20 rows per page; 100 is the documented maximum.
    page_size: int = 100


# GET /jobs/localization is the only list endpoint Lingo.dev exposes — single jobs and
# job groups are retrievable by id only. The API has no server-side timestamp filters
# (only engineId/status), so only full refresh is supported.
LINGO_DEV_ENDPOINTS: dict[str, LingoDevEndpointConfig] = {
    "jobs": LingoDevEndpointConfig(name="jobs", path="/jobs/localization"),
}

ENDPOINTS = tuple(LINGO_DEV_ENDPOINTS.keys())
