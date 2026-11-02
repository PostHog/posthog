from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "electricity_retail_sales": {
        "description": "Monthly electricity sales, prices, revenue, and customer counts by state and sector.",
        "docs_url": "https://www.eia.gov/opendata/browser/electricity/retail-sales",
        "columns": {
            "period": "First day of the reporting month, at midnight UTC.",
            "stateid": "State or census region code.",
            "sectorid": "Customer sector code.",
            "price": "Average electricity price in cents per kilowatt-hour.",
            "sales": "Electricity sold in million kilowatt-hours.",
            "revenue": "Revenue from electricity sales in million dollars.",
            "customers": "Number of electricity customers.",
        },
    },
    "natural_gas_prices": {
        "description": "Monthly natural gas prices by area and price series.",
        "docs_url": "https://www.eia.gov/opendata/browser/natural-gas/pri/sum",
        "columns": {
            "period": "First day of the reporting month, at midnight UTC.",
            "series": "EIA series identifier.",
            "duoarea": "Geographic area code.",
            "product": "Energy product code.",
            "process": "Price category code.",
            "value": "Reported price in the units supplied with the row.",
            "units": "Unit of measurement for the price.",
        },
    },
    "retail_fuel_prices": {
        "description": "Weekly retail gasoline and diesel prices by area and product.",
        "docs_url": "https://www.eia.gov/opendata/browser/petroleum/pri/gnd",
        "columns": {
            "period": "Reporting date for the week, at midnight UTC.",
            "series": "EIA series identifier.",
            "duoarea": "Geographic area code.",
            "product": "Fuel product code.",
            "process": "Price category code.",
            "value": "Reported price in the units supplied with the row.",
            "units": "Unit of measurement for the price.",
        },
    },
}
