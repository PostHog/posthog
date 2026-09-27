from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Fireworks AI control-plane API (https://docs.fireworks.ai/api-reference). A Google AIP-style
# resource API: every collection is a GET under https://api.fireworks.ai/v1/accounts/{account_id}/
# returning {"<collection>": [...], "nextPageToken": "...", "totalSize": n} with pageToken/pageSize
# pagination (pageSize max 200, default 50). Objects carry a globally unique read-only `name`
# (e.g. "accounts/my-account/models/my-model") plus read-only `createTime`/`updateTime`.
#
# The spec documents an AIP-160 `filter` param on every list endpoint, but the filterable fields
# are not enumerated and we could not verify server-side timestamp filtering against the live API,
# so every collection table ships full refresh only. Collections are small per account (jobs,
# datasets, deployments), so a full fetch is cheap.
#
# `billingUsage` is the exception to both shapes. It is a report rather than a collection: it takes
# a required startTime/endTime window, does not paginate, and answers with three parallel arrays of
# daily aggregation buckets instead of one keyed collection. Because that window is a documented
# server-side filter, it is the only table here that can sync incrementally.
#
# The apiKeys collection is deliberately excluded: it is nested per user and its schema carries
# key material (`key`, `prefix`) that must not land in a warehouse table.

PAGE_SIZE = 200

# Schema name of the billingUsage report. The transport routes it to its own iterator because no
# part of the AIP list shape (collection key, page token, resource `name`) applies to it.
ACCOUNT_USAGE = "account_usage"

# billingUsage rejects a window wider than this ("end_time must not be more than 31 days after
# start_time"), so a backfill walks the requested range in chunks of at most this many days.
USAGE_MAX_WINDOW_DAYS = 31

# How far back the first usage sync reaches when there is no incremental watermark to start from.
# The API documents no history floor, so a year bounds the initial backfill at twelve requests and
# every later run resumes from the watermark instead.
USAGE_BACKFILL_DAYS = 365


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class FireworksAIEndpointConfig:
    name: str
    # Collection segment under /v1/accounts/{account_id}/, e.g. "supervisedFineTuningJobs".
    path: str
    # Key the row array is nested under in the response (matches the collection segment). None for
    # the billingUsage report, whose three arrays the transport explodes itself.
    data_key: str | None = None
    # Field to partition Delta files by. Must be a STABLE field (createTime, never updateTime).
    partition_key: str = "createTime"
    # AIP resource names are globally unique full paths, so `name` is the primary key for every
    # collection. The usage report has no resource name and keys on a synthesized `id` instead.
    primary_keys: list[str] = field(default_factory=lambda: ["name"])
    # Empty unless the endpoint exposes a verified server-side time filter.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


FIREWORKS_AI_ENDPOINTS: dict[str, FireworksAIEndpointConfig] = {
    "models": FireworksAIEndpointConfig(name="models", path="models", data_key="models"),
    "datasets": FireworksAIEndpointConfig(name="datasets", path="datasets", data_key="datasets"),
    "deployments": FireworksAIEndpointConfig(name="deployments", path="deployments", data_key="deployments"),
    "deployed_models": FireworksAIEndpointConfig(
        name="deployed_models", path="deployedModels", data_key="deployedModels"
    ),
    "routers": FireworksAIEndpointConfig(name="routers", path="routers", data_key="routers"),
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
    # "List Reinforcement Fine-tuning Steps" in the API reference. The collection is named
    # rlorTrainerJobs after the RLOR trainer that runs each step, so the path and the data key do
    # not resemble the table name.
    "reinforcement_fine_tuning_steps": FireworksAIEndpointConfig(
        name="reinforcement_fine_tuning_steps",
        path="rlorTrainerJobs",
        data_key="rlorTrainerJobs",
    ),
    "dpo_jobs": FireworksAIEndpointConfig(name="dpo_jobs", path="dpoJobs", data_key="dpoJobs"),
    "batch_inference_jobs": FireworksAIEndpointConfig(
        name="batch_inference_jobs", path="batchInferenceJobs", data_key="batchInferenceJobs"
    ),
    "evaluation_jobs": FireworksAIEndpointConfig(
        name="evaluation_jobs", path="evaluationJobs", data_key="evaluationJobs"
    ),
    "evaluators": FireworksAIEndpointConfig(name="evaluators", path="evaluators", data_key="evaluators"),
    "users": FireworksAIEndpointConfig(name="users", path="users", data_key="users"),
    ACCOUNT_USAGE: FireworksAIEndpointConfig(
        name=ACCOUNT_USAGE,
        path="billingUsage",
        partition_key="startTime",
        primary_keys=["id"],
        incremental_fields=[_datetime_incremental_field("startTime")],
    ),
}

ENDPOINTS = tuple(FIREWORKS_AI_ENDPOINTS.keys())
