from dataclasses import dataclass
from datetime import timedelta

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# `/spend/logs/v2` caps `page_size` at 1000; the key and user lists cap their page size at 100.
SPEND_LOGS_PAGE_SIZE = 1000
LIST_PAGE_SIZE = 100

# Spend logs are read one day at a time, because LiteLLM pages with a SQL offset and a deep offset
# over a busy proxy's whole history gets slow.
SPEND_LOGS_WINDOW = timedelta(days=1)

SPEND_LOGS_FIELD = "startTime"


@dataclass(frozen=True)
class LiteLLMEndpointConfig:
    name: str
    path: str
    primary_key: str
    data_selector: str
    page_size_param: str | None = None
    partition_key: str | None = None


LITELLM_ENDPOINTS: dict[str, LiteLLMEndpointConfig] = {
    "spend_logs": LiteLLMEndpointConfig(
        name="spend_logs",
        path="/spend/logs/v2",
        primary_key="request_id",
        data_selector="data",
        partition_key=SPEND_LOGS_FIELD,
    ),
    "keys": LiteLLMEndpointConfig(
        name="keys",
        path="/key/list",
        primary_key="token",
        data_selector="keys",
        page_size_param="size",
        partition_key="created_at",
    ),
    "users": LiteLLMEndpointConfig(
        name="users",
        path="/user/list",
        primary_key="user_id",
        data_selector="users",
        page_size_param="page_size",
        partition_key="created_at",
    ),
    "teams": LiteLLMEndpointConfig(name="teams", path="/team/list", primary_key="team_id", data_selector="$"),
    "models": LiteLLMEndpointConfig(name="models", path="/model/info", primary_key="model_id", data_selector="data"),
}

ENDPOINTS = tuple(LITELLM_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "spend_logs": [
        {
            "label": SPEND_LOGS_FIELD,
            "type": IncrementalFieldType.DateTime,
            "field": SPEND_LOGS_FIELD,
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
}
