from dataclasses import dataclass
from datetime import timedelta

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

# Every list endpoint, `/spend/logs/v2` included, caps its page size at 100 before LiteLLM 1.95.
SPEND_LOGS_PAGE_SIZE = 100
LIST_PAGE_SIZE = 100

# LiteLLM 1.84 counts every log that matches a request's date range, on every request, so each
# request covers at most this much time after the cursor.
SPEND_LOGS_WINDOW = timedelta(days=1)

SPEND_LOGS_FIELD = "startTime"
SPEND_LOGS_LOOKBACK_SECONDS = 3600


@dataclass(frozen=True)
class LiteLLMEndpointConfig:
    name: str
    path: str
    primary_key: str
    data_selector: str
    page_size_param: str | None = None
    # The response has no page count, so a page with fewer rows than asked for is the last one.
    pages_without_total: bool = False
    partition_key: str | None = None
    # Off for responses that carry credentials before the row map masks them.
    capture: bool = True


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
        capture=False,
    ),
    "users": LiteLLMEndpointConfig(
        name="users",
        path="/user/list",
        primary_key="user_id",
        data_selector="users",
        page_size_param="page_size",
        partition_key="created_at",
    ),
    "teams": LiteLLMEndpointConfig(
        name="teams",
        path="/v2/team/list",
        primary_key="team_id",
        data_selector="teams",
        page_size_param="page_size",
        capture=False,
    ),
    "models": LiteLLMEndpointConfig(name="models", path="/model/info", primary_key="model_id", data_selector="data"),
    "budgets": LiteLLMEndpointConfig(
        name="budgets",
        path="/budget/list",
        primary_key="budget_id",
        data_selector="$",
        partition_key="created_at",
    ),
    "organizations": LiteLLMEndpointConfig(
        name="organizations",
        path="/organization/list",
        primary_key="organization_id",
        data_selector="$",
        partition_key="created_at",
        capture=False,
    ),
    "tags": LiteLLMEndpointConfig(name="tags", path="/tag/list", primary_key="name", data_selector="$"),
    "customers": LiteLLMEndpointConfig(
        name="customers",
        path="/customer/list",
        primary_key="user_id",
        data_selector="$",
        page_size_param="page_size",
        pages_without_total=True,
    ),
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
