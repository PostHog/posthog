from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

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
    incremental_field: str
    numeric_fields: tuple[str, ...]


ENDPOINTS: dict[str, FiscalDataEndpoint] = {
    "rates_of_exchange": FiscalDataEndpoint(
        path="v1/accounting/od/rates_of_exchange",
        primary_keys=("record_date", "country_currency_desc", "effective_date", "src_line_nbr"),
        incremental_field="effective_date",
        numeric_fields=("exchange_rate",),
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
}
