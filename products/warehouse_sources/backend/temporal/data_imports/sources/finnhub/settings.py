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
    # The response is parallel arrays keyed by field name (Finnhub's candle shape) that are
    # zipped back into one row per index.
    columnar: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["symbol"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable field used to partition the Delta table. Either a date string or epoch seconds,
    # and it must never change for a given row — so never an `updated`/`lastSeen` style field.
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
    # The window params are UNIX seconds rather than "YYYY-MM-DD".
    epoch_window: bool = False
    lookback_days: int = 365
    forward_days: int = 0
    # Documented hard cap on rows one call can return. Finnhub gives these endpoints no
    # pagination, so a response at the cap means the window was silently truncated.
    max_rows_per_request: Optional[int] = None
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
    "financials_reported": FinnhubEndpointConfig(
        name="financials_reported",
        path="/stock/financials-reported",
        data_key="data",
        requires_symbol=True,
        # `accessNumber` is the SEC accession number of the filing the report was taken from.
        primary_keys=["symbol", "accessNumber"],
        partition_key="endDate",
        fixed_params={"freq": "annual"},
        windowed=True,
        # Financial statements are only worth having with several years of history behind them.
        lookback_days=1825,
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "endDate",
                "type": IncrementalFieldType.DateTime,
                "field": "endDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="As-reported income statement, balance sheet and cash flow per annual filing, for each configured symbol. Supports incremental sync on the period end date.",
    ),
    "stock_candles": FinnhubEndpointConfig(
        name="stock_candles",
        path="/stock/candle",
        columnar=True,
        requires_symbol=True,
        primary_keys=["symbol", "t"],
        partition_key="t",
        # Daily bars are adjusted for splits; intraday resolutions are not, and Finnhub caps
        # them at a month per call.
        fixed_params={"resolution": "D"},
        windowed=True,
        epoch_window=True,
        # `to` lands on midnight, so reach a day past it to take in today's bar.
        forward_days=1,
        lookback_days=730,
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "t",
                "type": IncrementalFieldType.DateTime,
                "field": "t",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        description="Daily OHLCV candles for each configured symbol. Supports incremental sync on the candle timestamp.",
    ),
    "sec_filings": FinnhubEndpointConfig(
        name="sec_filings",
        path="/stock/filings",
        requires_symbol=True,
        primary_keys=["symbol", "accessNumber"],
        partition_key="filedDate",
        windowed=True,
        max_rows_per_request=250,
        should_sync_default=False,
        incremental_fields=[
            {
                "label": "filedDate",
                "type": IncrementalFieldType.DateTime,
                "field": "filedDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        description="Index of a company's SEC filings, for each configured symbol. Supports incremental sync on the filed date.",
    ),
    "insider_transactions": FinnhubEndpointConfig(
        name="insider_transactions",
        path="/stock/insider-transactions",
        data_key="data",
        requires_symbol=True,
        # Form 4 rows carry no id, and one insider can report several lines on the same day —
        # commonly a sale filled at different prices. Key on everything that identifies a line
        # except `share`, which is the running holding rather than part of the transaction.
        primary_keys=[
            "symbol",
            "name",
            "transactionDate",
            "filingDate",
            "transactionCode",
            "change",
            "transactionPrice",
        ],
        partition_key="transactionDate",
        windowed=True,
        max_rows_per_request=100,
        should_sync_default=False,
        incremental_fields=[
            # Finnhub documents `from`/`to` without saying which date they filter. A filing
            # date is never earlier than the transaction it reports, so watermarking on
            # `transactionDate` asks for a superset either way — watermarking on `filingDate`
            # would skip transactions under the other reading.
            {
                "label": "transactionDate",
                "type": IncrementalFieldType.DateTime,
                "field": "transactionDate",
                "field_type": IncrementalFieldType.Date,
            },
        ],
        description="Insider buy and sell transactions reported on Form 3/4/5, for each configured symbol. Supports incremental sync on the transaction date.",
    ),
}

ENDPOINTS = tuple(FINNHUB_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FINNHUB_ENDPOINTS.items() if config.incremental_fields
}
