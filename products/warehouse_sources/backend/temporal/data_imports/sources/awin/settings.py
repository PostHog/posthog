from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

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

# `accounts` is a single top-level call. Every other endpoint fans out over the publisher accounts
# the token can see, over its advertiser accounts, or over each publisher's joined programmes. The
# last kind is for publisher-scoped paths that also require an advertiserId query param.
AwinEndpointKind = Literal["accounts", "publisher_fanout", "advertiser_fanout", "publisher_programme_fanout"]

# Awin's aggregated report endpoints require a `region` query param naming the account's market
# (there is no "all regions" value). Options and default ("GB") match Awin's own API docs.
REGION_OPTIONS: list[tuple[str, str]] = [
    ("GB", "United Kingdom"),
    ("US", "United States"),
    ("AT", "Austria"),
    ("AU", "Australia"),
    ("BE", "Belgium"),
    ("BR", "Brazil (BRL)"),
    ("BU", "Brazil (USD)"),
    ("CA", "Canada"),
    ("CH", "Switzerland"),
    ("DE", "Germany"),
    ("DK", "Denmark"),
    ("ES", "Spain"),
    ("FI", "Finland"),
    ("FR", "France"),
    ("IE", "Ireland"),
    ("IT", "Italy"),
    ("NL", "Netherlands"),
    ("NO", "Norway"),
    ("PL", "Poland"),
    ("SE", "Sweden"),
]
DEFAULT_REGION = "GB"


@frozen
class AwinEndpointConfig:
    name: str
    kind: AwinEndpointKind
    # Path relative to https://api.awin.com. `{publisher_id}` / `{advertiser_id}` is substituted per
    # account for fan-out endpoints.
    path: str
    primary_keys: list[str]
    # For `accounts` the payload is wrapped as {"accounts": [...]}; `commission_groups` wraps its rows
    # under "commissionGroups". Every other list endpoint returns a bare JSON array.
    data_key: Optional[str] = None
    # The payload is a single object that becomes one row, rather than a list of them.
    single_row: bool = False
    # Top-level fields copied onto every row extracted from `data_key`. Awin hangs the rate validity
    # window off the commission groups envelope rather than off each group.
    envelope_keys: list[str] = field(default_factory=list)
    # Inject the fan-out identifiers onto each row so the parent identifier is present in the table
    # (and in composite primary keys). Transactions and the performance reports already carry them.
    inject_publisher_id: bool = False
    inject_advertiser_id: bool = False
    # Static query params sent on every request for this endpoint (e.g. the programmes relationship
    # filter).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Whether the endpoint takes a startDate/endDate window. Transactions and reports do; the lookup
    # endpoints don't.
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
    # Whether this endpoint needs the account's `region` in its query params. Only Awin's
    # publisher-side aggregated report requires it; the advertiser-side report does not.
    requires_region: bool = False
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
    "programme_details": AwinEndpointConfig(
        name="programme_details",
        kind="publisher_programme_fanout",
        path="/publishers/{publisher_id}/programmedetails",
        primary_keys=["publisherId", "advertiserId"],
        # One programme per call, so the whole payload (commission range, KPIs, programme info) is
        # a single row.
        single_row=True,
        inject_publisher_id=True,
        inject_advertiser_id=True,
        extra_params={"relationship": "joined"},
        # One request per joined programme, so it is slow for a publisher in many programmes.
        should_sync_default=False,
    ),
    "commission_groups": AwinEndpointConfig(
        name="commission_groups",
        kind="publisher_programme_fanout",
        path="/publishers/{publisher_id}/commissiongroups",
        # groupId is documented as unique across advertisers, but the rates attached to it are the
        # ones this publisher gets, so the publisher belongs in the key too.
        primary_keys=["publisherId", "advertiserId", "groupId"],
        data_key="commissionGroups",
        envelope_keys=["ratesStart", "ratesEnd"],
        # Without this Awin returns each condition's type and operator but not the values it
        # compares against, which is the part a query needs.
        extra_params={"extraConditionsDetails": "true"},
        inject_publisher_id=True,
        inject_advertiser_id=True,
        should_sync_default=False,
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
        requires_region=True,
    ),
    "reports_publisher": AwinEndpointConfig(
        name="reports_publisher",
        kind="advertiser_fanout",
        path="/advertisers/{advertiser_id}/reports/publisher",
        # The advertiser-side counterpart of reports_advertiser; rows carry both ids already. Awin's
        # spec shows a {body, statusCode, statusCodeValue} wrapper on both reports, but that is a
        # Spring ResponseEntity artifact, so the service returns the bare array reports_advertiser
        # already reads.
        primary_keys=["advertiserId", "publisherId"],
        date_windowed=True,
        date_format="%Y-%m-%d",
        report_lookback_days=DEFAULT_REPORT_LOOKBACK_DAYS,
    ),
    "advertiser_publishers": AwinEndpointConfig(
        name="advertiser_publishers",
        kind="advertiser_fanout",
        path="/advertisers/{advertiser_id}/publishers",
        primary_keys=["advertiserId", "id"],
        inject_advertiser_id=True,
    ),
}

ENDPOINTS = tuple(AWIN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AWIN_ENDPOINTS.items()
}
