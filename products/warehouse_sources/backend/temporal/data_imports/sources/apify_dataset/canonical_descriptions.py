from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# `dataset_items` ships no entry: its columns are whatever the Actor stored, so there is nothing
# fixed to describe.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "actor_runs": {
        "description": "One row per Actor run on the account, with its status, timings, compute cost and the storages it wrote.",
        "docs_url": "https://docs.apify.com/api/v2/actor-runs-get",
        "columns": {
            "id": "Unique identifier of the run.",
            "actId": "Identifier of the Actor that was run. Joins to the actors table.",
            "userId": "Identifier of the user who owns the run.",
            "actorTaskId": "Identifier of the saved Actor task the run came from, or null when the Actor was run directly.",
            "status": "Lifecycle status of the run, such as READY, RUNNING, SUCCEEDED, FAILED, TIMED-OUT or ABORTED.",
            "startedAt": "Time the run started.",
            "finishedAt": "Time the run finished, or null while it is still running.",
            "buildId": "Identifier of the Actor build the run executed.",
            "buildNumber": "Version of the Actor build the run executed, such as 0.1.1.",
            "meta": "Origin of the run, plus the schedule that started it when it was scheduled.",
            "usageTotalUsd": "Total cost of the run in US dollars. Hidden when the request is not authenticated.",
            "defaultDatasetId": "Identifier of the dataset the run stored its output in. Joins to the datasets table.",
            "defaultKeyValueStoreId": "Identifier of the key-value store the run wrote non-dataset output to.",
            "defaultRequestQueueId": "Identifier of the request queue the run crawled from.",
        },
    },
    "actors": {
        "description": "The Actors the account created or used, with build and run counts.",
        "docs_url": "https://docs.apify.com/api/v2/actors-get",
        "columns": {
            "id": "Unique identifier of the Actor. Matches actId on runs and datasets.",
            "createdAt": "Time the Actor was created.",
            "modifiedAt": "Time the Actor was last modified.",
            "name": "Technical name of the Actor, unique within its owner.",
            "username": "Username of the account that owns the Actor.",
            "title": "Human-readable name of the Actor.",
            "stats": "Aggregate counts for the Actor, including total builds, total runs, user counts over trailing windows and the time it last ran.",
        },
    },
    "datasets": {
        "description": "The account's datasets, including the unnamed ones an Actor run creates, with item counts and the run that produced them.",
        "docs_url": "https://docs.apify.com/api/v2/datasets-get",
        "columns": {
            "id": "Unique identifier of the dataset. This is the value the dataset_items table is configured with.",
            "name": "Name of the dataset. Datasets created by an Actor run are unnamed.",
            "userId": "Identifier of the user who owns the dataset.",
            "createdAt": "Time the dataset was created.",
            "modifiedAt": "Time the dataset was last written to.",
            "accessedAt": "Time the dataset was last read.",
            "itemCount": "Number of items stored in the dataset. Takes up to 5 seconds to catch up after a write.",
            "cleanItemCount": "Number of items excluding empty and hidden ones. Takes up to 5 seconds to catch up after a write.",
            "actId": "Identifier of the Actor whose run created the dataset, or null when it was created directly. Joins to the actors table.",
            "actRunId": "Identifier of the run that created the dataset, or null when it was created directly. Joins to the actor_runs table.",
            "title": "Human-readable name of the dataset.",
            "username": "Username of the account that owns the dataset.",
            "generalAccess": "Whether the dataset is restricted to its owner or readable more widely.",
            "stats": "Read and write counts for the dataset, plus its stored and uncompressed size in bytes.",
        },
    },
    "usage_monthly": {
        "description": "Platform usage and spend for the current monthly usage cycle, one row per day. The whole cycle is re-imported on every sync.",
        "docs_url": "https://docs.apify.com/api/v2/users-me-usage-monthly-get",
        "columns": {
            "date": "Day the usage was recorded on.",
            "serviceUsage": "Usage for that day, keyed by service name such as ACTOR_COMPUTE_UNITS.",
            "totalUsageCreditsUsd": "Total spend for that day in US dollars.",
            "usageCycleStartAt": "Start of the monthly usage cycle the day belongs to.",
            "usageCycleEndAt": "End of the monthly usage cycle the day belongs to.",
            "totalUsageCreditsUsdBeforeVolumeDiscount": "Spend for the whole cycle in US dollars, before any volume discount. Repeated on every day of the cycle.",
            "totalUsageCreditsUsdAfterVolumeDiscount": "Spend for the whole cycle in US dollars, after any volume discount. Repeated on every day of the cycle.",
        },
    },
}
