from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZonkaFeedbackEndpointConfig:
    name: str
    path: str
    # Zonka Feedback object IDs are unique within an account, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None


# Zonka Feedback v2.1 account-level list endpoints. All are full-refresh only: the public REST
# list endpoints expose page/page_size pagination but no documented server-side `updated_after`
# date cursor, so there is no genuine incremental cursor to advance.
ZONKA_FEEDBACK_ENDPOINTS: dict[str, ZonkaFeedbackEndpointConfig] = {
    "responses": ZonkaFeedbackEndpointConfig(name="responses", path="/responses"),
    "surveys": ZonkaFeedbackEndpointConfig(name="surveys", path="/surveys"),
    "contacts": ZonkaFeedbackEndpointConfig(name="contacts", path="/contacts"),
}

ENDPOINTS = tuple(ZONKA_FEEDBACK_ENDPOINTS.keys())

# Full refresh only — no endpoint exposes a server-side timestamp filter to drive incremental sync.
INCREMENTAL_FIELDS: dict[str, list] = {}
