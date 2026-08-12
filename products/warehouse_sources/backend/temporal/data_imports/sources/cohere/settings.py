from dataclasses import dataclass, field
from enum import Enum


class CoherePagination(Enum):
    # ?limit=&offset= — used by /datasets and /connectors. Terminate when a page returns
    # fewer rows than the page size.
    OFFSET = "offset"
    # ?page_size=&page_token= with a next_page_token in the body — used by /models and
    # /finetuning/finetuned-models. Terminate when the response omits the token.
    PAGE_TOKEN = "page_token"
    # Single unpaginated request returning every row — used by /embed-jobs.
    NONE = "none"


@dataclass
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
    "connectors": CohereEndpointConfig(
        name="connectors",
        path="/connectors",
        data_key="connectors",
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
    "finetuned_models": CohereEndpointConfig(
        name="finetuned_models",
        path="/finetuning/finetuned-models",
        data_key="finetuned_models",
        pagination=CoherePagination.PAGE_TOKEN,
    ),
    "embed_jobs": CohereEndpointConfig(
        name="embed_jobs",
        path="/embed-jobs",
        data_key="embed_jobs",
        pagination=CoherePagination.NONE,
        primary_keys=["job_id"],
    ),
}

ENDPOINTS = tuple(COHERE_ENDPOINTS.keys())
