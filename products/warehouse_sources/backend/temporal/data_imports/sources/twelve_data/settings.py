from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# Hard cap the API enforces on /time_series `outputsize`.
TIME_SERIES_PAGE_SIZE = 5000

# Bounds on import fan-out: every per-symbol table issues one request per configured symbol, and
# /time_series pages further toward the start date, so both dimensions need a ceiling. Enforced at
# config validation AND at sync time, so a previously stored config can't bypass them.
MAX_SYMBOLS = 100
MAX_TIME_SERIES_PAGES_PER_SYMBOL = 50

TIME_SERIES_ENDPOINT = "time_series"

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
    # JSON key holding the row list in the response body. None means the body itself is one row.
    data_key: str | None = None
    # Whether the endpoint is fetched once per configured symbol (vs one catalog-wide call).
    per_symbol: bool = False
    # Static query params sent on every request to the endpoint.
    params: dict[str, str] = field(default_factory=dict)
    partition_key: str | None = None


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
}

# Only /time_series exposes a genuine server-side timestamp filter (start_date); the catalog and
# fundamentals endpoints are full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{endpoint: [] for endpoint in ENDPOINTS},
    TIME_SERIES_ENDPOINT: [incremental_field("datetime")],
}
