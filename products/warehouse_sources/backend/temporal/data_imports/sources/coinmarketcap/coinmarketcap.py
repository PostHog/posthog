import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coinmarketcap.settings import (
    COINMARKETCAP_ENDPOINTS,
    PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# All requests go to CoinMarketCap's Pro API host.
COINMARKETCAP_BASE_URL = "https://pro-api.coinmarketcap.com"

# Header CoinMarketCap recommends for passing the Pro API key (over the query-string form).
API_KEY_HEADER = "X-CMC_PRO_API_KEY"


@dataclasses.dataclass
class CoinMarketCapResumeConfig:
    start: int


class CoinMarketCapPaginator(OffsetPaginator):
    """1-based offset/limit paginator with resume support.

    CoinMarketCap's list endpoints page on `start` (1-based) and `limit`. They don't
    return a usable total in the response, and an out-of-range `start` returns an empty
    `data` list with HTTP 200, so empty-/short-page detection is the reliable stop
    condition (`total_path=None`).
    """

    def __init__(self) -> None:
        super().__init__(
            limit=PAGE_SIZE,
            offset=1,  # `start` is 1-based; start=0 is rejected with a 400.
            offset_param="start",
            limit_param="limit",
            total_path=None,
        )

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if self._has_next_page:
            return {"start": self.offset}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        start = state.get("start")
        if start is not None:
            self.offset = int(start)
            self._has_next_page = True


def get_resource(endpoint: str) -> EndpointResource:
    config = COINMARKETCAP_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": config.data_selector,
            "path": config.path,
            "params": dict(config.extra_params),
        },
        "table_format": "delta",
    }


def coinmarketcap_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CoinMarketCapResumeConfig],
) -> SourceResponse:
    endpoint_config = COINMARKETCAP_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": COINMARKETCAP_BASE_URL,
            # Going through APIKeyAuth (rather than raw headers) registers the key
            # for value-based log redaction.
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": API_KEY_HEADER,
                "location": "header",
            },
            "paginator": CoinMarketCapPaginator(),
            # CoinMarketCap's API responds directly, so there's no legitimate redirect
            # to follow; pinning it off keeps traffic on the validated host.
            "session": make_tracked_session(redact_values=(api_key,), allow_redirects=False),
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"start": resume_config.start}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles
        # cleanup once the sync finishes. Saving happens after each page is yielded,
        # so a crash re-fetches the last page rather than skipping it.
        if state and state.get("start") is not None:
            resumable_source_manager.save_state(CoinMarketCapResumeConfig(start=int(state["start"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe the zero-credit `/v1/key/info` endpoint to confirm the key is genuine.

    Returns (is_valid, error_message). A 200 means the key authenticates; 401 means it's
    missing or invalid. Any other status / network error is surfaced verbatim.
    """
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{COINMARKETCAP_BASE_URL}/v1/key/info",
            headers={API_KEY_HEADER: api_key},
            timeout=10,
            allow_redirects=False,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid CoinMarketCap API key"
    return False, f"CoinMarketCap returned an unexpected status code: {response.status_code}"
