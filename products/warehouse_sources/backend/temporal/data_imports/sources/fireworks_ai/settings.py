from dataclasses import dataclass, field

# Fireworks AI control-plane API (https://docs.fireworks.ai/api-reference). A Google AIP-style
# resource API: every collection is a GET under https://api.fireworks.ai/v1/accounts/{account_id}/
# returning {"<collection>": [...], "nextPageToken": "...", "totalSize": n} with pageToken/pageSize
# pagination (pageSize max 200, default 50). Objects carry a globally unique read-only `name`
# (e.g. "accounts/my-account/models/my-model") plus read-only `createTime`/`updateTime`.
#
# The spec documents an AIP-160 `filter` param on every list endpoint, but the filterable fields
# are not enumerated and we could not verify server-side timestamp filtering against the live API,
# so every table ships full refresh only. Collections are small per account (jobs, datasets,
# deployments), so a full fetch is cheap.
#
# The apiKeys collection is deliberately excluded: it is nested per user and its schema carries
# key material (`key`, `prefix`) that must not land in a warehouse table.

PAGE_SIZE = 200


@dataclass
class FireworksAIEndpointConfig:
    name: str
    # Collection segment under /v1/accounts/{account_id}/, e.g. "supervisedFineTuningJobs".
    path: str
    # Key the row array is nested under in the response (matches the collection segment).
    data_key: str
    # Field to partition Delta files by. Must be a STABLE field (createTime, never updateTime).
    partition_key: str = "createTime"
    # AIP resource names are globally unique full paths, so `name` is the primary key everywhere.
    primary_keys: list[str] = field(default_factory=lambda: ["name"])


FIREWORKS_AI_ENDPOINTS: dict[str, FireworksAIEndpointConfig] = {
    "models": FireworksAIEndpointConfig(name="models", path="models", data_key="models"),
    "datasets": FireworksAIEndpointConfig(name="datasets", path="datasets", data_key="datasets"),
    "deployments": FireworksAIEndpointConfig(name="deployments", path="deployments", data_key="deployments"),
    "deployed_models": FireworksAIEndpointConfig(
        name="deployed_models", path="deployedModels", data_key="deployedModels"
    ),
    "supervised_fine_tuning_jobs": FireworksAIEndpointConfig(
        name="supervised_fine_tuning_jobs",
        path="supervisedFineTuningJobs",
        data_key="supervisedFineTuningJobs",
    ),
    "reinforcement_fine_tuning_jobs": FireworksAIEndpointConfig(
        name="reinforcement_fine_tuning_jobs",
        path="reinforcementFineTuningJobs",
        data_key="reinforcementFineTuningJobs",
    ),
    "batch_inference_jobs": FireworksAIEndpointConfig(
        name="batch_inference_jobs", path="batchInferenceJobs", data_key="batchInferenceJobs"
    ),
    "evaluation_jobs": FireworksAIEndpointConfig(
        name="evaluation_jobs", path="evaluationJobs", data_key="evaluationJobs"
    ),
    "evaluators": FireworksAIEndpointConfig(name="evaluators", path="evaluators", data_key="evaluators"),
    "users": FireworksAIEndpointConfig(name="users", path="users", data_key="users"),
}

ENDPOINTS = tuple(FIREWORKS_AI_ENDPOINTS.keys())
