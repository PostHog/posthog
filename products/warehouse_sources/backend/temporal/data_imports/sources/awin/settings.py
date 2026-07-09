from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Awin caps the transactions/report date windows at 31 days per request, so any range wider than
# this must be chunked. We use 30 to stay safely inside the (inclusive) limit.
MAX_WINDOW_DAYS = 30

# How far back the first transactions sync reaches when the user hasn't picked an incremental cursor
# yet (or on a full refresh). Bounds the initial backfill instead of walking all of history.
DEFAULT_BACKFILL_DAYS = 365

# Aggregated reports have no per-row timestamp to checkpoint on, so they're full-refresh snapshots
# over a fixed trailing window rather than an incremental scroll.
DEFAULT_REPORT_LOOKBACK_DAYS = 30

# `accounts` is a single top-level call; every other endpoint fans out over the publisher accounts
# the token can see (the publisherId is a path param).
AwinEndpointKind = Literal["accounts", "publisher_fanout"]


@dataclass
class AwinEndpointConfig:
    name: str
    kind: AwinEndpointKind
    # Path relative to https://api.awin.com. `{publisher_id}` is substituted per account for fan-out
    # endpoints.
    path: str
    primary_keys: list[str]
    # For `accounts` the payload is wrapped as {"accounts": [...]}. Every other endpoint returns a
    # bare JSON array.
    data_key: Optional[str] = None
    # Inject the fan-out publisherId onto each row so the parent identifier is present in the table
    # (and in composite primary keys). Transactions/reports already carry publisherId, so only the
    # programmes endpoint needs it.
    inject_publisher_id: bool = False
    # Static query params sent on every request for this endpoint (e.g. the programmes relationship
    # filter).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Whether the endpoint takes a startDate/endDate window. Transactions and reports do; accounts
    # and programmes don't.
    date_windowed: bool = False
    # Awin uses full ISO datetimes for transactions but date-only for the aggregated reports.
    date_format: str = "%Y-%m-%dT%H:%M:%S"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps the user-selected incremental field to Awin's `dateType` query param, which chooses which
    # timestamp the server windows on (transaction vs validation).
    date_type_by_field: dict[str, str] = field(default_factory=dict)
    partition_key: Optional[str] = None
    # Trailing window (in days) for full-refresh report snapshots. `None` for non-report endpoints.
    report_lookback_days: Optional[int] = None
    should_sync_default: bool = True


AWIN_ENDPOINTS: dict[str, AwinEndpointConfig] = {
    "accounts": AwinEndpointConfig(
        name="accounts",
        kind="accounts",
        path="/accounts",
        data_key="accounts",
        primary_keys=["accountId"],
    ),
    "programmes": AwinEndpointConfig(
        name="programmes",
        kind="publisher_fanout",
        path="/publishers/{publisher_id}/programmes",
        primary_keys=["publisherId", "id"],
        inject_publisher_id=True,
        # Only the advertiser programmes the publisher has actually joined; the default (all
        # programmes in the network) would be enormous and mostly irrelevant.
        extra_params={"relationship": "joined"},
    ),
    "transactions": AwinEndpointConfig(
        name="transactions",
        kind="publisher_fanout",
        path="/publishers/{publisher_id}/transactions/",
        primary_keys=["id"],
        date_windowed=True,
        date_format="%Y-%m-%dT%H:%M:%S",
        incremental_fields=[
            {
                "label": "transactionDate",
                "type": IncrementalFieldType.DateTime,
                "field": "transactionDate",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "validationDate",
                "type": IncrementalFieldType.DateTime,
                "field": "validationDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        date_type_by_field={"transactionDate": "transaction", "validationDate": "validation"},
        partition_key="transactionDate",
    ),
    "reports_advertiser": AwinEndpointConfig(
        name="reports_advertiser",
        kind="publisher_fanout",
        path="/publishers/{publisher_id}/reports/advertiser",
        # Aggregated per advertiser within the requested window; publisherId is injected so the same
        # advertiser under different publisher accounts stays distinct.
        primary_keys=["publisherId", "advertiserId"],
        inject_publisher_id=True,
        date_windowed=True,
        date_format="%Y-%m-%d",
        report_lookback_days=DEFAULT_REPORT_LOOKBACK_DAYS,
    ),
}

ENDPOINTS = tuple(AWIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AWIN_ENDPOINTS.items()
}
