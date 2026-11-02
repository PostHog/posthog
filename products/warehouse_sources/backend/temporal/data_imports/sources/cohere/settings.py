from dataclasses import field
from enum import Enum
from typing import Any

from posthog.dataclasses import frozen

# Cohere versions its API in the URL path. Most list endpoints live only on /v1/, while batches
# live only on /v2/, so the path version is fixed per endpoint rather than chosen by the user.
COHERE_API_VERSION_V1 = "v1"
COHERE_API_VERSION_V2 = "v2"


class CoherePagination(Enum):
    # ?limit=&offset= — used by /datasets. Terminate when a page returns fewer rows than the
    # page size.
    OFFSET = "offset"
    # ?page_size=&page_token= with a next_page_token in the body — used by /models and /batches.
    # Terminate when the response omits the token.
    PAGE_TOKEN = "page_token"
    # Single unpaginated request returning every row — used by /embed-jobs.
    NONE = "none"


@frozen
class CohereEndpointConfig:
    name: str
    path: str
    # Envelope key holding the list of rows in the JSON response (e.g. {"datasets": [...]}).
    data_key: str
    pagination: CoherePagination
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable creation timestamp used for datetime partitioning. None for endpoints whose
    # objects expose no creation time (the model catalog), which skips partitioning.
    partition_key: str | None = "created_at"
    page_size: int = 100
    # Body key carrying the cursor for PAGE_TOKEN endpoints.
    next_token_key: str = "next_page_token"
    api_version: str = COHERE_API_VERSION_V1
    extra_params: dict[str, Any] = field(default_factory=dict)


# The list endpoints a user connecting Cohere actually wants to warehouse: syncable asset and
# job-history entities. Cohere is mostly an inference API; these are the objects with durable
# rows worth pulling. Every endpoint is full refresh only — see CohereSource.get_schemas for why.
COHERE_ENDPOINTS: dict[str, CohereEndpointConfig] = {
    "datasets": CohereEndpointConfig(
        name="datasets",
        path="/datasets",
        data_key="datasets",
        pagination=CoherePagination.OFFSET,
    ),
    # The model catalog has no per-model creation timestamp, so it can't be partitioned by one.
    "models": CohereEndpointConfig(
        name="models",
        path="/models",
        data_key="models",
        pagination=CoherePagination.PAGE_TOKEN,
        primary_keys=["name"],
        partition_key=None,
        page_size=1000,  # /models caps page_size at 1000
    ),
    "embed_jobs": CohereEndpointConfig(
        name="embed_jobs",
        path="/embed-jobs",
        data_key="embed_jobs",
        pagination=CoherePagination.NONE,
        primary_keys=["job_id"],
    ),
    "batches": CohereEndpointConfig(
        name="batches",
        path="/batches",
        data_key="batches",
        pagination=CoherePagination.PAGE_TOKEN,
        api_version=COHERE_API_VERSION_V2,
        page_size=1000,  # /batches caps page_size at 1000
        # An explicit, stable order keeps page boundaries steady while new batches are created mid-sync.
        extra_params={"order_by": "created_at"},
    ),
}

# Tables whose Cohere endpoint no longer exists. Dropping the name from COHERE_ENDPOINTS is what
# retires the table: schema discovery stops listing it, which disables syncing and leaves any
# already-imported rows in place. The reason lives here so a job that starts before the next
# discovery run explains itself rather than raising a KeyError.
# https://docs.cohere.com/docs/deprecations — the 2025-09-15 announcement retires connectors and
# all of fine-tuning across both the dashboard and the API. Both paths now answer 404.
RETIRED_ENDPOINTS: dict[str, str] = {
    "connectors": (
        "Cohere retired its connectors API on September 15, 2025, so the connectors table can't "
        "sync any more. Turn off syncing for this table."
    ),
    "finetuned_models": (
        "Cohere retired fine-tuning on September 15, 2025, so the finetuned models table can't "
        "sync any more. Turn off syncing for this table."
    ),
}

ENDPOINTS = tuple(COHERE_ENDPOINTS.keys())
