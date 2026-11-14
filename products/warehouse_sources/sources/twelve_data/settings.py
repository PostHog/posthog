from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, incremental_field

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Hard cap the API enforces on /time_series `outputsize`.
TIME_SERIES_PAGE_SIZE = 5000

# Bounds on import fan-out: every per-symbol table issues one request per configured symbol, and
# /time_series pages further toward the start date, so both dimensions need a ceiling. Enforced at
# config validation AND at sync time, so a previously stored config can't bypass them.
MAX_SYMBOLS = 100
MAX_TIME_SERIES_PAGES_PER_SYMBOL = 50

TIME_SERIES_ENDPOINT = "time_series"
MARKET_CAP_ENDPOINT = "market_cap"

# /market_cap accepts this `outputsize` (verified against the live API); a daily series is a few
# hundred rows per symbol, so one page usually holds the whole history.
MARKET_CAP_PAGE_SIZE = 5000
MAX_MARKET_CAP_PAGES_PER_SYMBOL = 10

# The market-wide calendars are synced over a rolling window around today, so the table holds
# recent and upcoming events rather than an ever-growing history.
CALENDAR_LOOKBACK_DAYS = 7
CALENDAR_LOOKAHEAD_DAYS = 30
# Calendars without a record cap are paged in pages of this size (500 is the documented maximum).
CALENDAR_PAGE_SIZE = 500
MAX_CALENDAR_PAGES = 20
# /earnings_calendar silently truncates at 1200 records, so the window is requested a week at a
# time, and a chunk that hits the cap is split in half until it fits or covers a single day.
EARNINGS_CALENDAR_RECORD_LIMIT = 1200
EARNINGS_CALENDAR_CHUNK_DAYS = 7

TIME_SERIES_INTERVALS = (
    "1min",
    "5min",
    "15min",
    "30min",
    "45min",
    "1h",
    "2h",
    "4h",
    "1day",
    "1week",
    "1month",
)

DEFAULT_TIME_SERIES_INTERVAL = "1day"


@dataclass(frozen=True)
class TwelveDataEndpointConfig:
    path: str
    primary_keys: list[str]
    # JSON key holding the rows in the response body: a list of rows, or one object for a single
    # row. None means the body itself is one row.
    data_key: str | None = None
    # Keys from the response `meta` object copied onto every row. `symbol` is always copied.
    meta_fields: tuple[str, ...] = ()
    # Whether the endpoint is fetched once per configured symbol (vs one catalog-wide call).
    per_symbol: bool = False
    # Static query params sent on every request to the endpoint.
    params: dict[str, str] = field(default_factory=dict)
    partition_key: str | None = None
    # Rows per request for endpoints paged with `page` and `outputsize`.
    page_size: int | None = None
    # Market-wide event calendar, requested over the rolling calendar window instead of per symbol.
    calendar: bool = False
    # Rows are grouped under date keys ({"2024-04-30": [...]}); the key becomes the row's `date`.
    date_keyed: bool = False
    # Records the API returns at most per request; a window that reaches it is split.
    record_limit: int | None = None
    chunk_days: int | None = None


ENDPOINTS: dict[str, TwelveDataEndpointConfig] = {
    # Reference catalogs — one request each, full refresh.
    "stocks": TwelveDataEndpointConfig(
        path="/stocks",
        data_key="data",
        # The same ticker is listed on many exchanges; the MIC code disambiguates the listing.
        primary_keys=["symbol", "mic_code"],
    ),
    "etfs": TwelveDataEndpointConfig(
        path="/etfs",
        data_key="data",
        primary_keys=["symbol", "mic_code"],
    ),
    "indices": TwelveDataEndpointConfig(
        path="/indices",
        data_key="data",
        primary_keys=["symbol", "mic_code"],
    ),
    "forex_pairs": TwelveDataEndpointConfig(
        path="/forex_pairs",
        data_key="data",
        primary_keys=["symbol"],
    ),
    "cryptocurrencies": TwelveDataEndpointConfig(
        path="/cryptocurrencies",
        data_key="data",
        primary_keys=["symbol"],
    ),
    "exchanges": TwelveDataEndpointConfig(
        path="/exchanges",
        data_key="data",
        primary_keys=["code"],
    ),
    # Per-symbol market data.
    TIME_SERIES_ENDPOINT: TwelveDataEndpointConfig(
        path="/time_series",
        data_key="values",
        per_symbol=True,
        primary_keys=["symbol", "datetime"],
        partition_key="datetime",
    ),
    "quotes": TwelveDataEndpointConfig(
        path="/quote",
        data_key=None,
        per_symbol=True,
        primary_keys=["symbol"],
    ),
    "dividends": TwelveDataEndpointConfig(
        path="/dividends",
        data_key="dividends",
        per_symbol=True,
        # Default `range` is only the most recent payout; `full` returns the whole history.
        params={"range": "full"},
        primary_keys=["symbol", "ex_date"],
    ),
    "splits": TwelveDataEndpointConfig(
        path="/splits",
        data_key="splits",
        per_symbol=True,
        params={"range": "full"},
        primary_keys=["symbol", "date"],
    ),
    "earnings": TwelveDataEndpointConfig(
        path="/earnings",
        data_key="earnings",
        per_symbol=True,
        # Default `outputsize` is only the most recent reports; 1000 is the documented maximum.
        params={"outputsize": "1000"},
        primary_keys=["symbol", "date"],
    ),
    "profiles": TwelveDataEndpointConfig(
        path="/profile",
        data_key=None,
        per_symbol=True,
        primary_keys=["symbol"],
    ),
    "statistics": TwelveDataEndpointConfig(
        path="/statistics",
        data_key="statistics",
        per_symbol=True,
        meta_fields=("currency",),
        primary_keys=["symbol"],
    ),
    # The default `outputsize` is only the 6 most recent statements. No maximum is documented;
    # 1000 returns the whole history (about 150 quarters for a large US company).
    "balance_sheets": TwelveDataEndpointConfig(
        path="/balance_sheet",
        data_key="balance_sheet",
        per_symbol=True,
        params={"period": "quarterly", "outputsize": "1000"},
        meta_fields=("currency", "period"),
        # `period` is in the key because a fiscal year end and its fourth quarter share a fiscal_date.
        primary_keys=["symbol", "period", "fiscal_date"],
    ),
    "cash_flows": TwelveDataEndpointConfig(
        path="/cash_flow",
        data_key="cash_flow",
        per_symbol=True,
        params={"period": "quarterly", "outputsize": "1000"},
        meta_fields=("currency", "period"),
        primary_keys=["symbol", "period", "fiscal_date"],
    ),
    "income_statements": TwelveDataEndpointConfig(
        path="/income_statement",
        data_key="income_statement",
        per_symbol=True,
        params={"period": "quarterly", "outputsize": "1000"},
        meta_fields=("currency", "period"),
        primary_keys=["symbol", "period", "fiscal_date"],
    ),
    MARKET_CAP_ENDPOINT: TwelveDataEndpointConfig(
        path="/market_cap",
        data_key="market_cap",
        per_symbol=True,
        page_size=MARKET_CAP_PAGE_SIZE,
        meta_fields=("currency",),
        primary_keys=["symbol", "date"],
        partition_key="date",
    ),
    # Only the top holders are returned, as a snapshot of the latest filings.
    "institutional_holders": TwelveDataEndpointConfig(
        path="/institutional_holders",
        data_key="institutional_holders",
        per_symbol=True,
        meta_fields=("currency",),
        primary_keys=["symbol", "entity_name"],
    ),
    "fund_holders": TwelveDataEndpointConfig(
        path="/fund_holders",
        data_key="fund_holders",
        per_symbol=True,
        meta_fields=("currency",),
        primary_keys=["symbol", "entity_name"],
    ),
    "direct_holders": TwelveDataEndpointConfig(
        path="/direct_holders",
        data_key="direct_holders",
        per_symbol=True,
        meta_fields=("currency",),
        primary_keys=["symbol", "entity_name"],
    ),
    # Market-wide event calendars.
    "earnings_calendar": TwelveDataEndpointConfig(
        path="/earnings_calendar",
        data_key="earnings",
        calendar=True,
        date_keyed=True,
        record_limit=EARNINGS_CALENDAR_RECORD_LIMIT,
        chunk_days=EARNINGS_CALENDAR_CHUNK_DAYS,
        primary_keys=["symbol", "mic_code", "date"],
    ),
    "dividends_calendar": TwelveDataEndpointConfig(
        path="/dividends_calendar",
        calendar=True,
        page_size=CALENDAR_PAGE_SIZE,
        primary_keys=["symbol", "mic_code", "ex_date"],
    ),
    "splits_calendar": TwelveDataEndpointConfig(
        path="/splits_calendar",
        calendar=True,
        page_size=CALENDAR_PAGE_SIZE,
        primary_keys=["symbol", "mic_code", "date"],
    ),
    "ipo_calendar": TwelveDataEndpointConfig(
        path="/ipo_calendar",
        calendar=True,
        date_keyed=True,
        primary_keys=["symbol", "mic_code", "date"],
    ),
}

# Only /time_series and /market_cap expose a genuine server-side timestamp filter (start_date); the
# catalog, fundamentals and calendar endpoints are full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{endpoint: [] for endpoint in ENDPOINTS},
    TIME_SERIES_ENDPOINT: [incremental_field("datetime")],
    MARKET_CAP_ENDPOINT: [incremental_field("date", IncrementalFieldType.Date)],
}
