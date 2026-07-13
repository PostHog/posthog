from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SmartreachEndpointConfig:
    name: str
    path: str
    # SmartReach nests the row list inside the `data` object under a per-endpoint key
    # (e.g. `data.prospects`, `data.campaigns`), so each endpoint records which key to read.
    data_key: str
    # SmartReach object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # exposes a genuine creation timestamp — never an "updated" field, which changes on edit.
    partition_key: Optional[str] = None


# SmartReach v1 API list endpoints. All are full-refresh only: while the prospects endpoint does
# expose `newer_than`/`older_than` epoch filters, we ship full refresh to avoid depending on
# ordering we cannot verify (see the implementing-warehouse-sources skill).
SMARTREACH_ENDPOINTS: dict[str, SmartreachEndpointConfig] = {
    "prospects": SmartreachEndpointConfig(name="prospects", path="/prospects", data_key="prospects"),
    "campaigns": SmartreachEndpointConfig(name="campaigns", path="/campaigns", data_key="campaigns"),
}

ENDPOINTS = tuple(SMARTREACH_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
