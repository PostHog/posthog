from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class KalshiEndpointConfig:
    name: str
    path: str
    data_key: str  # response wrapper key holding the array (e.g. "markets")
    primary_keys: list[str] = field(default_factory=lambda: ["ticker"])
    partition_key: Optional[str] = None  # stable creation-time field for datetime partitioning
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only trades exposes a server-side time filter (`min_ts`). Everything else accepts the param
    # and silently ignores it, so those endpoints are full-refresh only.
    supports_incremental: bool = False
    # Trades come back newest-first; every other endpoint is treated as ascending.
    newest_first: bool = False
    # `/series` returns the whole collection in one response with no `cursor` key.
    paginated: bool = True
    page_size: int = 200


def _created_time_field() -> list[IncrementalField]:
    return [
        {
            "label": "created_time",
            "type": IncrementalFieldType.DateTime,
            "field": "created_time",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


KALSHI_ENDPOINTS: dict[str, KalshiEndpointConfig] = {
    # Every market ever listed, one row per contract. `updated_time` moves but there is no filter
    # for it, so this is a full refresh; partition on the stable `created_time`.
    "markets": KalshiEndpointConfig(
        name="markets",
        path="/markets",
        data_key="markets",
        primary_keys=["ticker"],
        partition_key="created_time",
        page_size=1000,
    ),
    # Events group related markets (one election, one game). Keyed on `event_ticker`; carries no
    # creation timestamp, so no partitioning.
    "events": KalshiEndpointConfig(
        name="events",
        path="/events",
        data_key="events",
        primary_keys=["event_ticker"],
        page_size=200,
    ),
    # Series are the recurring templates events are minted from. The endpoint returns all of them
    # in a single unpaginated response.
    "series": KalshiEndpointConfig(
        name="series",
        path="/series",
        data_key="series",
        primary_keys=["ticker"],
        paginated=False,
    ),
    # The one genuinely incremental stream: every public trade, append-only, filtered server-side
    # with `min_ts` and returned newest-first.
    "trades": KalshiEndpointConfig(
        name="trades",
        path="/markets/trades",
        data_key="trades",
        primary_keys=["trade_id"],
        partition_key="created_time",
        incremental_fields=_created_time_field(),
        supports_incremental=True,
        newest_first=True,
        page_size=1000,
    ),
    # Real-world happenings Kalshi ties markets to (a court date, a scheduled release).
    "milestones": KalshiEndpointConfig(
        name="milestones",
        path="/milestones",
        data_key="milestones",
        primary_keys=["id"],
        page_size=200,
    ),
}

ENDPOINTS = tuple(KALSHI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in KALSHI_ENDPOINTS.items()
}
