from dataclasses import dataclass, field


@dataclass
class DockerhubEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Docker Hub management API v2 list endpoints (https://docs.docker.com/reference/api/hub/latest/).
# Both are full-refresh only: the Hub API exposes no server-side updated_after/since filter on
# repositories or tags, so there is no incremental cursor to advance (see the
# implementing-warehouse-sources skill). Tag rows carry a numeric `repository` id, not the repo
# name, so we inject `namespace` and `repository_name` into every tag row and key on those plus the
# tag name — tag names are only unique within their repository.
DOCKERHUB_ENDPOINTS: dict[str, DockerhubEndpointConfig] = {
    "repositories": DockerhubEndpointConfig(name="repositories", primary_keys=["namespace", "name"]),
    "tags": DockerhubEndpointConfig(name="tags", primary_keys=["namespace", "repository_name", "name"]),
}

ENDPOINTS = tuple(DOCKERHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
