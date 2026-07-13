from dataclasses import dataclass, field

# Together AI platform API (https://docs.together.ai/reference). Every list endpoint is a single
# GET under https://api.together.xyz/v1 that returns the whole collection in one response — no
# pagination parameters and no server-side timestamp filters are documented (verified against the
# official Python SDK, which reads each list in one request). That means every table is full
# refresh only; collections are small per account, so a full fetch is cheap.
#
# Response envelopes vary per endpoint: fine-tunes/files/endpoints wrap rows in {"data": [...]},
# while batches/evaluations/models return a bare JSON array. The transport handles both shapes.


@dataclass
class TogetherAIEndpointConfig:
    name: str
    # Path under the API root, e.g. "/fine-tunes".
    path: str
    # Field to partition Delta files by. Must be a STABLE field (created timestamp, never updated_at).
    partition_key: str = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Static query params sent with the request.
    params: dict[str, str] = field(default_factory=dict)


TOGETHER_AI_ENDPOINTS: dict[str, TogetherAIEndpointConfig] = {
    "fine_tunes": TogetherAIEndpointConfig(name="fine_tunes", path="/fine-tunes"),
    "batches": TogetherAIEndpointConfig(name="batches", path="/batches"),
    "files": TogetherAIEndpointConfig(name="files", path="/files"),
    # Only the account's dedicated endpoint deployments — the unfiltered list also includes every
    # public serverless model, which duplicates the models table.
    "endpoints": TogetherAIEndpointConfig(name="endpoints", path="/endpoints", params={"type": "dedicated"}),
    "evaluations": TogetherAIEndpointConfig(name="evaluations", path="/evaluations", primary_keys=["workflow_id"]),
    # The serverless model catalog: id, type, pricing, context length per model. Rows carry a
    # `created` unix timestamp instead of `created_at`.
    "models": TogetherAIEndpointConfig(name="models", path="/models", partition_key="created"),
}

ENDPOINTS = tuple(TOGETHER_AI_ENDPOINTS.keys())
