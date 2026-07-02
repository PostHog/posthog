from dataclasses import dataclass, field


@dataclass
class HuggingFaceEndpointConfig:
    name: str
    path: str
    # createdAt is immutable, so it's a stable partition key (unlike lastModified). Every Hub
    # repo object exposes it.
    partition_key: str = "createdAt"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `full=true` returns the richer object (e.g. pipeline_tag, library_name on models); harmless
    # on endpoints that don't add fields.
    full: bool = True


# The Hub exposes each repo kind as a list endpoint with identical query semantics
# (author filter, createdAt sort, Link-header cursor pagination). These three repo streams are
# what a user connecting their account actually wants to pull into the warehouse.
HUGGING_FACE_ENDPOINTS: dict[str, HuggingFaceEndpointConfig] = {
    "models": HuggingFaceEndpointConfig(name="models", path="/api/models"),
    "datasets": HuggingFaceEndpointConfig(name="datasets", path="/api/datasets"),
    "spaces": HuggingFaceEndpointConfig(name="spaces", path="/api/spaces"),
}

ENDPOINTS = tuple(HUGGING_FACE_ENDPOINTS.keys())
