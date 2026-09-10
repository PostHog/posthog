from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class FinnhubEndpointConfig:
    name: str
    path: str
    # JSON key the row array lives under (e.g. calendar endpoints wrap rows in
    # `ipoCalendar`/`earningsCalendar`). None means the response is parsed directly.
    data_key: Optional[str] = None
    # The response is a single JSON object yielded as one row (quote, profile, basic
    # financials) rather than a list.
    single_object: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["symbol"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field used to partition the Delta table. Must be a "YYYY-MM-DD" date string
    # (Finnhub's epoch-second timestamps aren't parsed by the datetime partitioner), and
    # must never change for a given row — so never an `updated`/`lastSeen` style field.
    partition_key: Optional[str] = None
    # Per-symbol fan-out: the endpoint needs a `symbol` query param and is queried once per
    # configured ticker, with the requested symbol injected into each emitted row.
    requires_symbol: bool = False
    # Static query params merged into every request for this endpoint (e.g. `metric=all`,
    # `category=general`). Keeps an endpoint's full request shape in this one config.
    fixed_params: dict[str, str] = field(default_factory=dict)
    # The endpoint accepts the source-level `exchange` query param (defaulting to US).
    exchange_param: bool = False
    # Windowed endpoints accept `from`/`to` (YYYY-MM-DD) range params. `lookback_days`
    # bounds how far back the initial/full window reaches; `forward_days` extends it into
    # the future for forward-looking calendars (scheduled IPOs / earnings).
    windowed: bool = False
    lookback_days: int = 365
    forward_days: int = 0
    should_sync_default: bool = True
    description: Optional[str] = None


# Endpoints chosen to mirror the canonical Finnhub stream set (cross-referenced against the
# Airbyte Finnhub connector) while staying on the free tier. Market-wide endpoints sync by
# default; per-symbol endpoints are opt-in since they only return data when the user has
# configured tickers.
FINNHUB_ENDPOINTS: dict[str, FinnhubEndpointConfig] = {
    # --- Market-wide reference / time-series (no symbol required) ---
    "stock_symbols": FinnhubEndpointConfig(
        name="stock_symbols",
        path="/stock/symbol",
        primary_keys=["symbol"],
        exchange_param=True,
        description="All tradable symbols for the configured exchange (default US). Full refresh.",
    ),
    "market_news": FinnhubEndpointConfig(
        name="market_news",
        path="/news",
        primary_keys=["id"],
        fixed_params={"category": "general"},
        # Market news only supports a `minId` cursor, not a server-side date filter, so it's
        # full refresh — the API returns the most recent general-market headlines each sync.
        description="Latest general market news. Full refresh.",
    ),
    "ipo_calendar": FinnhubEndpointConfig(
        name="ipo_calendar",
        path="/calendar/ipo",
        data_key="ipoCalendar",
        primary_keys=["symbol", "date"],
        partition_key="date",
        windowed=True,
        forward_days=180,
        # `date` is the scheduled IPO date and can be in the future, so an incremental
        # watermark on it would jump ahead and skip later-added near-term IPOs. Ship full
        # refresh over a rolling past+future window instead; merge dedupes on the key.
        description="Recent and upcoming IPOs over a rolling window. Full refresh.",
    ),
    "earnings_calendar": FinnhubEndpointConfig(
        name="earnings_calendar",
        path="/calendar/earnings",
        data_key="earningsCalendar",
        primary_keys=["symbol", "date"],
        partition_key="date",
        windowed=True,
        forward_days=180,
        # Same future-dating caveat as the IPO calendar — full refresh over a rolling window.
        description="Recent and upcoming company earnings over a rolling window. Full refresh.",
    ),
    "country": FinnhubEndpointConfig(
        name="country",
        path="/country",
        primary_keys=["code2"],
        description="Reference list of supported countries and their metadata. Full refresh.",
    ),
    # --- Per-symbol fan-out (requires configured tickers) ---
    "company_profile": FinnhubEndpointConfig(
        name="company_profile",
        path="/stock/profile2",
        single_object=True,
        requires_symbol=True,
        primary_keys=["symbol"],
        should_sync_default=False,
        description="Company profile for each configured symbol. Full refresh.",
    ),
    "quote": FinnhubEndpointConfig(
        name="quote",
        path="/quote",
        single_object=True,
        requires_symbol=True,
        primary_keys=["symbol"],
        should_sync_default=False,
        description="Latest real-time quote snapshot for each configured symbol. Full refresh.",
    ),
    "company_news": FinnhubEndpointConfig(
        name="company_news",
        path="/company-news",
        requires_symbol=True,
        # News articles can surface for more than one ticker, so the article id alone isn't
        # unique table-wide — key on (id, symbol).
        primary_keys=["id", "symbol"],
        windowed=True,
        lookback_days=365,
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "datetime",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        description="Company-specific news per configured symbol. Supports incremental sync on the published datetime.",
    ),
    "basic_financials": FinnhubEndpointConfig(
        name="basic_financials",
        path="/stock/metric",
        single_object=True,
        requires_symbol=True,
        primary_keys=["symbol"],
        fixed_params={"metric": "all"},
        should_sync_default=False,
        description="Basic financial metrics (valuation, margins, growth) per configured symbol. Full refresh.",
    ),
    "recommendation_trends": FinnhubEndpointConfig(
        name="recommendation_trends",
        path="/stock/recommendation",
        requires_symbol=True,
        primary_keys=["symbol", "period"],
        partition_key="period",
        should_sync_default=False,
        description="Analyst recommendation trends per configured symbol. Full refresh.",
    ),
    "earnings_surprises": FinnhubEndpointConfig(
        name="earnings_surprises",
        path="/stock/earnings",
        requires_symbol=True,
        primary_keys=["symbol", "period"],
        partition_key="period",
        should_sync_default=False,
        description="Historical EPS estimate vs actual surprises per configured symbol. Full refresh.",
    ),
}

ENDPOINTS = tuple(FINNHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FINNHUB_ENDPOINTS.items() if config.incremental_fields
}
