from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

CHURNKEY_BASE_URL = "https://api.churnkey.co/v1/data"

# The API caps a single response at 10,000 records. We page well below that so each
# response stays a reasonable size in memory (session records carry nested customer and
# presented-offer arrays).
DEFAULT_PAGE_SIZE = 1000


@dataclass
class ChurnkeyEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # Stable creation timestamp used for datetime partitioning. Never an `updatedAt`-style
    # field — partitions must not move once written.
    partition_key: Optional[str] = "createdAt"
    page_size: int = DEFAULT_PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)


CHURNKEY_ENDPOINTS: dict[str, ChurnkeyEndpointConfig] = {
    # Raw cancel-flow session records. The API exposes `startDate`/`endDate` date-window
    # filters, but neither a per-record `updated` cursor nor a documented server-side sort,
    # and we have no credentials to curl-verify that the window actually filters server-side
    # — so this ships full-refresh only (see PR notes). `_id` is a globally-unique Mongo
    # ObjectId, safe as the primary key.
    "Sessions": ChurnkeyEndpointConfig(
        name="Sessions",
        path="/sessions",
    ),
}

ENDPOINTS = tuple(CHURNKEY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CHURNKEY_ENDPOINTS.items()
}
