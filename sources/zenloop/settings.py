from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZenloopEndpointConfig:
    name: str
    path: str
    # The list of rows lives under a named key in the response envelope
    # (e.g. {"surveys": [...], "meta": {...}}), and the key differs per endpoint.
    response_key: str
    # Zenloop object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # actually exposes a creation timestamp.
    partition_key: Optional[str] = None


# Zenloop public API top-level list endpoints. All are full-refresh only: while Zenloop exposes
# date_from/date_to filters on some answer streams, the survey and property catalogs here have no
# reliable incremental cursor to advance, so a full refresh is the honest sync method.
ZENLOOP_ENDPOINTS: dict[str, ZenloopEndpointConfig] = {
    "surveys": ZenloopEndpointConfig(name="surveys", path="/surveys", response_key="surveys"),
    "survey_groups": ZenloopEndpointConfig(name="survey_groups", path="/survey_groups", response_key="survey_groups"),
    "properties": ZenloopEndpointConfig(name="properties", path="/properties", response_key="properties"),
}

ENDPOINTS = tuple(ZENLOOP_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
