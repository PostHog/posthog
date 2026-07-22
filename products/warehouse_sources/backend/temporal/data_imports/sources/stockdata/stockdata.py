import logging
import dataclasses
from datetime import date, datetime
from typing import Any, Optional

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.stockdata.settings import STOCKDATA_ENDPOINTS

logger = logging.getLogger(__name__)

STOCKDATA_BASE_URL = "https://api.stockdata.org/v1"
# StockData.org caps any paginated news result set at 20,000 records (limit × page); requesting
# beyond it can't return more rows, so pagination stops there and logs the truncation.
MAX_NEWS_RESULTS = 20_000


@dataclasses.dataclass
class StockDataResumeConfig:
    # Number of the next news page to fetch — StockData.org uses page-number pagination.
    next_page: int


def _format_date(value: Any) -> str:
    """Format an incremental cursor for the `date_from` filter (StockData.org expects YYYY-MM-DD)."""
    # datetime is a subclass of date, so this covers both.
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # A stored string cursor is already an ISO timestamp/date — keep just the date portion.
    return str(value)[:10]


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor for `published_after` (accepted down to YYYY-MM-DDTHH:MM:SS)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    # A stored string cursor is an ISO timestamp — drop any sub-second/timezone suffix.
    return str(value)[:19]


def _flatten_ohlcv(row: dict[str, Any]) -> dict[str, Any]:
    """EOD/intraday rows arrive as `{date, ticker, data: {open, high, ...}}` — lift the nested
    OHLCV object into the row root so the table gets proper columns."""
    nested = row.get("data")
    if not isinstance(nested, dict):
        return row
    flat = {key: value for key, value in row.items() if key != "data"}
    flat.update(nested)
    return flat


class StockDataNewsPaginator(PageNumberPaginator):
    """Page-number paginator that stops on the documented 20,000-result cap.

    The news response's `meta` block carries `found` (total matches), `limit` (page size), and
    `page`, so the paginator stops after the last real page instead of paying an extra empty-page
    request, and terminates cleanly at the result-set cap instead of erroring past it.
    """

    def __init__(self) -> None:
        super().__init__(base_page=1, page_param="page", stop_after_empty_page=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if data is None or len(data) == 0:
            self._has_next_page = False
            return

        self.page += 1

        try:
            body = response.json()
        except ValueError:
            body = None
        meta = body.get("meta") if isinstance(body, dict) else None
        if isinstance(meta, dict):
            found = meta.get("found")
            limit = meta.get("limit")
            page = meta.get("page")
            if (
                isinstance(found, int)
                and isinstance(limit, int)
                and isinstance(page, int)
                and not isinstance(limit, bool)
                and limit > 0
            ):
                fetched = page * limit
                if fetched >= found:
                    self._has_next_page = False
                    return
                if fetched >= MAX_NEWS_RESULTS:
                    logger.info(
                        "StockData.org news pagination reached the API's %s-result cap; %s matching "
                        "articles were not fetched. Older articles sync as the incremental watermark advances.",
                        MAX_NEWS_RESULTS,
                        found - fetched,
                    )
                    self._has_next_page = False
                    return

        self._has_next_page = True


def stockdata_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StockDataResumeConfig],
    symbols: str | None = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = STOCKDATA_ENDPOINTS[endpoint]
    normalized_symbols = _normalize_symbols(symbols)

    if config.requires_symbols and not normalized_symbols:
        # Selecting a price table with no symbols is a permanent misconfiguration; fail loud with
        # a fix-it message rather than issuing a request that can never make progress.
        raise ValueError(
            f"StockData.org API error [missing_symbols]: the '{endpoint}' table requires one or more "
            "symbols. Add symbols to the source configuration, then resync."
        )

    params: dict[str, Any] = dict(config.params)
    if (config.requires_symbols or config.accepts_symbols) and normalized_symbols:
        params["symbols"] = normalized_symbols
    if config.incremental_param and db_incremental_field_last_value is not None:
        if config.incremental_param == "published_after":
            params["published_after"] = _format_datetime(db_incremental_field_last_value)
        else:
            params["date_from"] = _format_date(db_incremental_field_last_value)

    resource: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            "data_selector": "data",
            # A 200 body without `data` means an error envelope or a changed shape — fail loud,
            # don't sync 0 rows.
            "data_selector_required": True,
        },
    }
    if config.flatten_data:
        resource["data_map"] = _flatten_ohlcv

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": STOCKDATA_BASE_URL,
            # api_token rides in the query string (the API's only auth method); the framework auth
            # redacts its value from every logged URL, captured sample, and raised error message.
            "auth": {"type": "api_key", "api_key": api_token, "name": "api_token", "location": "query"},
            "paginator": StockDataNewsPaginator() if config.paginated else "single_page",
        },
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(StockDataResumeConfig(next_page=int(state["page"])))

    rest_resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    # An empty result set can arrive as `"data": {}` rather than `"data": []` — drop the stray
    # empty object instead of syncing it as a junk row.
    rest_resource.add_filter(bool)

    partition_kwargs: dict[str, Any] = {}
    if config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: rest_resource,
        primary_keys=config.primary_keys,
        # Price feeds are requested with sort=asc; news is served newest-first and its sort order
        # can't be flipped, so it declares desc and the watermark checkpoints at end of sync.
        sort_mode=config.sort_mode,
        **partition_kwargs,
    )


def _normalize_symbols(symbols: str | None) -> str:
    if not symbols:
        return ""
    return ",".join(symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip())


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    # `/entity/type/list` is a static reference endpoint available on every plan and takes no
    # params, so it's the cheapest probe that the token is genuine (one request against plans
    # with daily request quotas).
    session = make_tracked_session(redact_values=(api_token,))
    try:
        response = session.get(f"{STOCKDATA_BASE_URL}/entity/type/list", params={"api_token": api_token}, timeout=10)
    except Exception:
        return False, "Could not connect to StockData.org. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 402:
        # The token is genuine — the plan's usage limit is just exhausted right now. Don't block
        # source creation on a quota that resets.
        return True, None
    if response.status_code == 401:
        return False, "Invalid StockData.org API token"
    return False, f"StockData.org returned an unexpected response (HTTP {response.status_code})"
