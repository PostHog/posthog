import dataclasses

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The time-series feeds carry a per-row `date`. Marketstack windows them server-side with the
# `date_from` / `date_to` query params, so those endpoints sync incrementally on `date`. EOD and
# intraday rows carry a full timestamp; splits and dividends carry a calendar date.
_EOD_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.DateTime,
        "field": "date",
        "field_type": IncrementalFieldType.DateTime,
    },
]
_DATE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.Date,
        "field": "date",
        "field_type": IncrementalFieldType.Date,
    },
]


@dataclasses.dataclass
class MarketstackEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Time-series endpoints require a `symbols` query param; reference tables ignore it.
    requires_symbols: bool = False
    # Empty list = full refresh only (no server-side date filter).
    incremental_fields: list[IncrementalField] = dataclasses.field(default_factory=list)
    default_incremental_field: str | None = None
    # Stable datetime column for datetime partitioning (`date` never changes for a given row).
    partition_key: str | None = None
    description: str | None = None


MARKETSTACK_ENDPOINTS: dict[str, MarketstackEndpointConfig] = {
    "eod": MarketstackEndpointConfig(
        name="eod",
        path="/eod",
        # A symbol trades on one exchange per row; the same symbol can appear on multiple exchanges,
        # so the exchange MIC is part of the key to keep it unique table-wide.
        primary_keys=["symbol", "exchange", "date"],
        requires_symbols=True,
        incremental_fields=_EOD_INCREMENTAL_FIELDS,
        default_incremental_field="date",
        partition_key="date",
        description="End-of-day (daily OHLCV) stock prices per symbol, including adjusted prices, split factor, and dividend. Requires symbols. Incremental on date.",
    ),
    "intraday": MarketstackEndpointConfig(
        name="intraday",
        path="/intraday",
        primary_keys=["symbol", "exchange", "date"],
        requires_symbols=True,
        incremental_fields=_EOD_INCREMENTAL_FIELDS,
        default_incremental_field="date",
        partition_key="date",
        description="Intraday (intra-day interval) stock prices per symbol. Requires symbols and a paid plan. Incremental on date.",
    ),
    "splits": MarketstackEndpointConfig(
        name="splits",
        path="/splits",
        primary_keys=["symbol", "date"],
        requires_symbols=True,
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
        default_incremental_field="date",
        partition_key="date",
        description="Historical stock split factors per symbol. Requires symbols. Incremental on date.",
    ),
    "dividends": MarketstackEndpointConfig(
        name="dividends",
        path="/dividends",
        primary_keys=["symbol", "date"],
        requires_symbols=True,
        incremental_fields=_DATE_INCREMENTAL_FIELDS,
        default_incremental_field="date",
        partition_key="date",
        description="Historical dividend payouts per symbol. Requires symbols. Incremental on date.",
    ),
    "tickers": MarketstackEndpointConfig(
        name="tickers",
        path="/tickers",
        primary_keys=["symbol"],
        description="Reference table of supported stock tickers with name, exchange, and EOD/intraday availability. Full refresh.",
    ),
    "exchanges": MarketstackEndpointConfig(
        name="exchanges",
        path="/exchanges",
        primary_keys=["mic"],
        description="Reference table of supported stock exchanges with MIC/acronym codes, country, and timezone. Full refresh.",
    ),
    "currencies": MarketstackEndpointConfig(
        name="currencies",
        path="/currencies",
        primary_keys=["code"],
        description="Reference table of supported currencies with ISO code, symbol, and name. Full refresh.",
    ),
    "timezones": MarketstackEndpointConfig(
        name="timezones",
        path="/timezones",
        primary_keys=["timezone"],
        description="Reference table of supported timezones with abbreviation and daylight-saving abbreviation. Full refresh.",
    ),
}

ENDPOINTS = tuple(MARKETSTACK_ENDPOINTS.keys())
