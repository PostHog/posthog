from typing import Literal

from sources.sdk import IncrementalField, frozen, incremental_field

BASE_URL = "https://api.retellai.com"
PAGE_SIZE = 100
INCREMENTAL_LOOKBACK_SECONDS = 3600


@frozen
class RetellAIEndpoint:
    path: str
    primary_key: str
    method: Literal["GET", "POST"] = "GET"
    pagination_location: Literal["query", "json"] = "query"
    paginated: bool = True
    partition_key: str | None = None


ENDPOINTS: dict[str, RetellAIEndpoint] = {
    "calls": RetellAIEndpoint(
        path="/{api_version}/list-calls",
        primary_key="call_id",
        method="POST",
        pagination_location="json",
        partition_key="start_timestamp",
    ),
    "agents": RetellAIEndpoint(path="/v2/list-agents", primary_key="agent_id", method="POST"),
    "chats": RetellAIEndpoint(
        path="/{api_version}/list-chats",
        primary_key="chat_id",
        method="POST",
        pagination_location="json",
        partition_key="start_timestamp",
    ),
    "phone_numbers": RetellAIEndpoint(path="/v2/list-phone-numbers", primary_key="phone_number"),
    "voices": RetellAIEndpoint(path="/list-voices", primary_key="voice_id", paginated=False),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "calls": [incremental_field("start_timestamp")],
    "chats": [incremental_field("start_timestamp")],
}
