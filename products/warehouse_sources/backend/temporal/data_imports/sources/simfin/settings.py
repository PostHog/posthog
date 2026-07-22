import dataclasses
from typing import Literal, Optional

# SimFin Web API v3 (https://backend.simfin.com/api/v3) is plain REST/JSON authenticated with an
# `Authorization: api-key <KEY>` header. There is no pagination on any of the endpoints below and no
# server-side change cursor (`updated_after`/`since`), so every table is full refresh only. The
# `start`/`end` params on statements/prices filter by the *record's* own date, and price history is
# split-adjusted retroactively, so they cannot safely drive incremental sync.
#
# The "compact" response format is columnar (`columns` + `data` arrays, wrapped per company for the
# ticker-scoped endpoints) — each `kind` below tells the transport how to reshape it into flat rows.
ParseKind = Literal[
    "companies",
    "company_details",
    "statements",
    "prices",
    "common_shares",
    "weighted_shares",
]

# All fiscal periods SimFin models. Requested explicitly (rather than relying on an undocumented
# server default) so quarterly, annual, and half-year/nine-month interim reports all land.
ALL_PERIODS = "q1,q2,q3,q4,fy,h1,h2,nine_month"


@dataclasses.dataclass
class SimFinEndpointConfig:
    name: str
    # Path relative to the versioned API base, e.g. "companies/statements/compact".
    path: str
    kind: ParseKind
    # Unique across the whole table. Ticker-scoped endpoints fan out over the user's configured
    # tickers, and every reshaped row carries the company `id`, so it's always part of the key.
    primary_keys: list[str]
    # Static query params for this endpoint (e.g. which statement type to request).
    params: Optional[dict[str, str]] = None
    # Whether the endpoint is requested once per configured ticker. `companies/list` is the only
    # account-wide endpoint; everything else is scoped to a ticker.
    fan_out_tickers: bool = True
    # A stable date column used for datetime partitioning. Never a mutable field. None for
    # small/snapshot tables (company catalog and details).
    partition_key: Optional[str] = None
    description: Optional[str] = None
    should_sync_default: bool = True


SIMFIN_ENDPOINTS: dict[str, SimFinEndpointConfig] = {
    "companies": SimFinEndpointConfig(
        name="companies",
        path="companies/list",
        kind="companies",
        primary_keys=["id"],
        fan_out_tickers=False,
        description="Catalog of every company in the SimFin database (SimFin ID, ticker, name, ISIN, sector and industry). One row per company. Full refresh.",
    ),
    "company_details": SimFinEndpointConfig(
        name="company_details",
        path="companies/general/compact",
        kind="company_details",
        primary_keys=["id"],
        description="Detailed company profile (market, fiscal-year end, employee count, business description) for each configured ticker. One row per company. Full refresh.",
    ),
    "income_statements": SimFinEndpointConfig(
        name="income_statements",
        path="companies/statements/compact",
        kind="statements",
        params={"statements": "pl", "period": ALL_PERIODS},
        primary_keys=["id", "fiscal_year", "fiscal_period"],
        partition_key="report_date",
        description="Standardized profit & loss statements for each configured ticker, all fiscal years and periods. One row per company, fiscal year and period. Full refresh.",
    ),
    "balance_sheets": SimFinEndpointConfig(
        name="balance_sheets",
        path="companies/statements/compact",
        kind="statements",
        params={"statements": "bs", "period": ALL_PERIODS},
        primary_keys=["id", "fiscal_year", "fiscal_period"],
        partition_key="report_date",
        description="Standardized balance sheets for each configured ticker, all fiscal years and periods. One row per company, fiscal year and period. Full refresh.",
    ),
    "cash_flow_statements": SimFinEndpointConfig(
        name="cash_flow_statements",
        path="companies/statements/compact",
        kind="statements",
        params={"statements": "cf", "period": ALL_PERIODS},
        primary_keys=["id", "fiscal_year", "fiscal_period"],
        partition_key="report_date",
        description="Standardized cash-flow statements for each configured ticker, all fiscal years and periods. One row per company, fiscal year and period. Full refresh.",
    ),
    "derived_ratios": SimFinEndpointConfig(
        name="derived_ratios",
        path="companies/statements/compact",
        kind="statements",
        params={"statements": "derived", "period": ALL_PERIODS},
        primary_keys=["id", "fiscal_year", "fiscal_period"],
        partition_key="report_date",
        description="Derived ratios and indicators (EBITDA, free cash flow, margins, per-share figures) for each configured ticker, all fiscal years and periods. Full refresh.",
        should_sync_default=False,
    ),
    "share_prices": SimFinEndpointConfig(
        name="share_prices",
        path="companies/prices/compact",
        kind="prices",
        primary_keys=["id", "date"],
        partition_key="date",
        description="Daily share prices (split-adjusted) with volume and dividends for each configured ticker. One row per company and trading day. Full refresh.",
    ),
    "common_shares_outstanding": SimFinEndpointConfig(
        name="common_shares_outstanding",
        path="companies/common-shares-outstanding",
        kind="common_shares",
        primary_keys=["id", "date"],
        description="Point-in-time common shares outstanding for each configured ticker. One row per company and change date. Full refresh.",
        should_sync_default=False,
    ),
    "weighted_shares_outstanding": SimFinEndpointConfig(
        name="weighted_shares_outstanding",
        path="companies/weighted-shares-outstanding",
        kind="weighted_shares",
        primary_keys=["id", "date", "fiscal_year", "period"],
        description="Basic and diluted weighted shares outstanding per fiscal period for each configured ticker. One row per company, fiscal year and period. Full refresh.",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(SIMFIN_ENDPOINTS.keys())
