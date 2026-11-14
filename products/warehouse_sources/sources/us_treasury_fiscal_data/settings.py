from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/"
API_DOCS_URL = "https://fiscaldata.treasury.gov/api-documentation/"
PAGE_SIZE = 1000
ACCESS_ERROR = (
    "US Treasury Fiscal Data refused access. This public API needs no key. Try again later or contact support."
)


@frozen
class FiscalDataEndpoint:
    path: str
    primary_keys: tuple[str, ...]
    incremental_field: str | None
    numeric_fields: tuple[str, ...]
    date_fields: tuple[str, ...] = ("record_date",)
    integer_fields: tuple[str, ...] = ("src_line_nbr",)
    partition_key: str = "record_date"


ENDPOINTS: dict[str, FiscalDataEndpoint] = {
    "rates_of_exchange": FiscalDataEndpoint(
        path="v1/accounting/od/rates_of_exchange",
        primary_keys=("record_date", "country_currency_desc", "effective_date", "src_line_nbr"),
        incremental_field="effective_date",
        numeric_fields=("exchange_rate",),
        date_fields=("record_date", "effective_date"),
    ),
    "avg_interest_rates": FiscalDataEndpoint(
        path="v2/accounting/od/avg_interest_rates",
        primary_keys=("record_date", "security_type_desc", "security_desc"),
        incremental_field="record_date",
        numeric_fields=("avg_interest_rate_amt",),
    ),
    "debt_to_penny": FiscalDataEndpoint(
        path="v2/accounting/od/debt_to_penny",
        primary_keys=("record_date",),
        incremental_field="record_date",
        numeric_fields=("debt_held_public_amt", "intragov_hold_amt", "tot_pub_debt_out_amt"),
    ),
    "interest_expense": FiscalDataEndpoint(
        path="v2/accounting/od/interest_expense",
        primary_keys=("record_date", "src_line_nbr"),
        incremental_field="record_date",
        numeric_fields=("month_expense_amt", "fytd_expense_amt"),
    ),
    "mts_table_1": FiscalDataEndpoint(
        path="v1/accounting/mts/mts_table_1",
        primary_keys=("record_date", "src_line_nbr"),
        incremental_field="record_date",
        numeric_fields=("current_month_gross_rcpt_amt", "current_month_gross_outly_amt", "current_month_dfct_sur_amt"),
    ),
    # Each release moves the latest years of estimates to its own record_date and drops them
    # from older releases, so record_date is not stable per row and the table is full refresh only.
    "ofs2_estimated_ownership_treasury_securities": FiscalDataEndpoint(
        path="v1/accounting/tb/ofs2_estimated_ownership_treasury_securities",
        primary_keys=("end_of_month", "securities_owner"),
        incremental_field=None,
        numeric_fields=("securities_bil_amt",),
        date_fields=("record_date", "end_of_month"),
        integer_fields=(),
        partition_key="end_of_month",
    ),
    # Auction rows are published before their results and filled in later under the same
    # record_date, and the API filters on no other date, so this table is full refresh only.
    "auctions_query": FiscalDataEndpoint(
        path="v1/accounting/od/auctions_query",
        primary_keys=("cusip", "auction_date"),
        incremental_field=None,
        # Includes the INTEGER-typed columns: the API sends some of them with decimals.
        numeric_fields=(
            "accrued_int_per100",
            "accrued_int_per1000",
            "adj_accrued_int_per1000",
            "adj_price",
            "allocation_pctage",
            "allocation_pctage_decimals",
            "avg_med_discnt_rate",
            "avg_med_investment_rate",
            "avg_med_discnt_margin",
            "avg_med_yield",
            "bid_to_cover_ratio",
            "comp_accepted",
            "comp_bid_decimals",
            "comp_tendered",
            "currently_outstanding",
            "direct_bidder_accepted",
            "direct_bidder_tendered",
            "est_pub_held_mat_by_type_amt",
            "fima_noncomp_accepted",
            "fima_noncomp_tendered",
            "frn_index_determination_rate",
            "high_discnt_rate",
            "high_investment_rate",
            "high_price",
            "high_discnt_margin",
            "high_yield",
            "index_ratio_on_issue_date",
            "indirect_bidder_accepted",
            "indirect_bidder_tendered",
            "int_rate",
            "low_discnt_rate",
            "low_investment_rate",
            "low_price",
            "low_discnt_margin",
            "low_yield",
            "max_comp_award",
            "max_noncomp_award",
            "max_single_bid",
            "min_bid_amt",
            "min_strip_amt",
            "min_to_issue",
            "multiples_to_bid",
            "multiples_to_issue",
            "nlp_exclusion_amt",
            "nlp_reporting_threshold",
            "noncomp_accepted",
            "offering_amt",
            "primary_dealer_accepted",
            "primary_dealer_tendered",
            "ref_cpi_on_dated_date",
            "ref_cpi_on_issue_date",
            "soma_accepted",
            "soma_holdings",
            "soma_tendered",
            "spread",
            "std_int_payment_per1000",
            "tiin_conversion_factor_per1000",
            "total_accepted",
            "total_tendered",
            "treas_retail_accepted",
            "unadj_accrued_int_per1000",
            "unadj_price",
        ),
        date_fields=(
            "record_date",
            "auction_date",
            "issue_date",
            "maturity_date",
            "announcemt_date",
            "back_dated_date",
            "call_date",
            "called_date",
            "dated_date",
            "first_int_payment_date",
            "frn_index_determination_date",
            "mat_date",
            "original_dated_date",
            "original_issue_date",
        ),
        integer_fields=(),
    ),
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": endpoint.incremental_field,
            "field": endpoint.incremental_field,
            "type": IncrementalFieldType.Date,
            "field_type": IncrementalFieldType.Date,
        }
    ]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.incremental_field is not None
}
