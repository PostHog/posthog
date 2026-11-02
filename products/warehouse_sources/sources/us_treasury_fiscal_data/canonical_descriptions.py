from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "rates_of_exchange": {
        "description": "Quarterly Treasury exchange rates, including amendments with separate effective dates.",
        "docs_url": "https://fiscaldata.treasury.gov/datasets/treasury-reporting-rates-exchange/",
        "columns": {
            "record_date": "Date of the published quarterly report.",
            "country": "Country associated with the exchange rate.",
            "currency": "Currency associated with the exchange rate.",
            "country_currency_desc": "Combined country and currency description.",
            "exchange_rate": "Units of foreign currency per US dollar.",
            "effective_date": "Date when the rate takes effect, including amendments.",
            "src_line_nbr": "Row number in the source report.",
        },
    },
    "avg_interest_rates": {
        "description": "Monthly average interest rates on outstanding Treasury securities, grouped by security type.",
        "docs_url": "https://fiscaldata.treasury.gov/datasets/average-interest-rates-treasury-securities/",
        "columns": {
            "record_date": "Date of the reported interest rates.",
            "security_type_desc": "Classification of the security as marketable or nonmarketable.",
            "security_desc": "Type of Treasury debt instrument.",
            "avg_interest_rate_amt": "Average interest rate as a percentage, based on interest payments and total debt.",
            "src_line_nbr": "Row number in the source report.",
        },
    },
    "debt_to_penny": {
        "description": "Daily total federal debt, split between public holdings and government accounts.",
        "docs_url": "https://fiscaldata.treasury.gov/datasets/debt-to-the-penny/",
        "columns": {
            "record_date": "Date of the reported debt balance.",
            "debt_held_public_amt": "Debt held outside federal government accounts, in US dollars.",
            "intragov_hold_amt": "Treasury securities held by federal government accounts, in US dollars.",
            "tot_pub_debt_out_amt": "Total outstanding public debt, in US dollars.",
            "src_line_nbr": "Row number in the source report.",
        },
    },
}
