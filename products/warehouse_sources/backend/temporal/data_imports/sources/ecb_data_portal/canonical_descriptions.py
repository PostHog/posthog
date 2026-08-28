from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "eur_exchange_rates": {
        "description": "Daily ECB reference exchange rates for the euro against other currencies, published each business day around 16:00 CET.",
        "docs_url": "https://data.ecb.europa.eu/data/data-categories/exchange-rates",
        "columns": {
            "KEY": "The full SDMX series key identifying the currency pair and rate type.",
            "FREQ": "Observation frequency (D = daily).",
            "CURRENCY": "ISO currency code being quoted against the euro.",
            "CURRENCY_DENOM": "Denominator currency (EUR for all reference rates).",
            "EXR_TYPE": "Exchange rate type (SP00 = spot rate).",
            "TIME_PERIOD": "The date the rate applies to.",
            "OBS_VALUE": "Units of CURRENCY per one euro.",
            "OBS_STATUS": "Observation status flag (A = normal value).",
            "UNIT": "Currency the rate is expressed in.",
        },
    },
    "key_interest_rates": {
        "description": "ECB key interest rates: the main refinancing rate, deposit facility rate, and marginal lending facility rate, by date of change.",
        "docs_url": "https://data.ecb.europa.eu/data/data-categories/monetary-policy",
        "columns": {
            "KEY": "The full SDMX series key identifying the rate type.",
            "REF_AREA": "Reference area (U2 = euro area, changing composition).",
            "PROVIDER_FM_ID": "Which key interest rate this row is for: DFR (deposit facility), MLFR (marginal lending facility), MRR_FR (main refinancing, fixed rate), MRR_MBR (main refinancing, minimum bid rate).",
            "TIME_PERIOD": "The date the rate took effect.",
            "OBS_VALUE": "The interest rate, in percent.",
        },
    },
    "hicp_inflation": {
        "description": "Euro area HICP (Harmonised Index of Consumer Prices) overall index, annual rate of change, not seasonally adjusted.",
        "docs_url": "https://data.ecb.europa.eu/data/data-categories/prices-and-costs",
        "columns": {
            "KEY": "The full SDMX series key.",
            "REF_AREA": "Reference area (U2 = euro area, changing composition).",
            "ICP_ITEM": "COICOP item code (000000 = overall index / all items).",
            "TIME_PERIOD": "The month the observation covers (YYYY-MM).",
            "OBS_VALUE": "Annual percentage rate of change of the HICP overall index.",
        },
    },
}
