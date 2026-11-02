from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalFieldType

BASE_URL = "https://app.promptingco.com/api/v1/"
PAGE_SIZE = 100


@frozen
class PromptingCompanyEndpoint:
    path: str
    data_selector: str
    scope: str
    product_scoped: bool = True
    paginated: bool = False
    total_pages_path: str | None = None
    primary_key: str = "id"
    partition_key: str = "createdAt"


ENDPOINTS = {
    "published_content": PromptingCompanyEndpoint(
        path="content",
        data_selector="data.items",
        scope="content:read",
        paginated=True,
        total_pages_path="data.totalPages",
    ),
    "prompt_suggestions": PromptingCompanyEndpoint(
        path="prompt-suggestions", data_selector="data", scope="prompts:read"
    ),
    "simulation_runs": PromptingCompanyEndpoint(
        path="agent-simulation/runs",
        data_selector="data.runs",
        scope="simulations:read",
        product_scoped=False,
        paginated=True,
    ),
    "share_of_voice": PromptingCompanyEndpoint(
        path="analytics/sov/timeseries",
        data_selector="data.timeSeries",
        scope="analytics:read",
        primary_key="date",
        partition_key="date",
    ),
}

INCREMENTAL_FIELDS = {"share_of_voice": [incremental_field("date", IncrementalFieldType.Date)]}

AUTH_ERROR = "The Prompting Company API key is invalid or expired. Create a new key in your organization settings."
PERMISSION_ERROR = (
    "The Prompting Company API key lacks a required read scope. Check the scopes for your selected tables."
)
