from dataclasses import dataclass, field


@dataclass
class FireworksAIEndpointConfig:
    name: str
    # Path segment appended after `/v1/accounts/{account_id}` (e.g. "/models").
    path: str
    # Key under which the list of objects is returned in the JSON body. Fireworks names it after
    # the trailing path segment (e.g. `/models` -> "models", `/supervisedFineTuningJobs` -> ...).
    data_key: str
    # Resource `name` (e.g. "accounts/acme/models/llama-v3") is globally unique across the account.
    primary_keys: list[str] = field(default_factory=lambda: ["name"])
    # Stable creation timestamp used for datetime partitioning. Every list resource exposes a
    # read-only `createTime`; never partition on `updateTime` (it shifts and rewrites partitions).
    partition_key: str | None = "createTime"
    should_sync_default: bool = True


# Control-plane list endpoints under https://api.fireworks.ai/v1/accounts/{account_id}. Each is a
# Google AIP-style resource collection paginated with pageSize/pageToken and returning
# {"<collection>": [...], "nextPageToken": "...", "totalSize": N}.
FIREWORKS_AI_ENDPOINTS: dict[str, FireworksAIEndpointConfig] = {
    "models": FireworksAIEndpointConfig(
        name="models",
        path="/models",
        data_key="models",
    ),
    "deployments": FireworksAIEndpointConfig(
        name="deployments",
        path="/deployments",
        data_key="deployments",
    ),
    "datasets": FireworksAIEndpointConfig(
        name="datasets",
        path="/datasets",
        data_key="datasets",
    ),
    "supervised_fine_tuning_jobs": FireworksAIEndpointConfig(
        name="supervised_fine_tuning_jobs",
        path="/supervisedFineTuningJobs",
        data_key="supervisedFineTuningJobs",
    ),
    "reinforcement_fine_tuning_jobs": FireworksAIEndpointConfig(
        name="reinforcement_fine_tuning_jobs",
        path="/reinforcementFineTuningJobs",
        data_key="reinforcementFineTuningJobs",
    ),
    "evaluation_jobs": FireworksAIEndpointConfig(
        name="evaluation_jobs",
        path="/evaluationJobs",
        data_key="evaluationJobs",
    ),
}

ENDPOINTS = tuple(FIREWORKS_AI_ENDPOINTS.keys())
