from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_REGIONAL_INCOME_COLUMNS = {
    "Code": "BEA statistic code, combining the table name and line code (e.g. SAINC1-3).",
    "GeoFips": "Geographic FIPS code for the area (e.g. a state or county FIPS code).",
    "GeoName": "Human-readable name of the geographic area.",
    "TimePeriod": "Year the statistic applies to.",
    "CL_UNIT": "Unit of measure for the statistic (e.g. Dollars, Persons).",
    "UNIT_MULT": "Base-10 exponent to apply to DataValue (e.g. 3 for thousands, 6 for millions).",
    "DataValue": "The statistic's value, in the unit and multiplier given by CL_UNIT/UNIT_MULT.",
    "NoteRef": "Reference to a footnote in the BEA release describing this or related values.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "StatePersonalIncomeSummary": {
        "description": "BEA Regional dataset, table SAINC1: annual personal income, population, and per capita personal income for every US state.",
        "docs_url": "https://apps.bea.gov/regional/docs/regionalregdata.cfm?param=SAINC1",
        "columns": _REGIONAL_INCOME_COLUMNS,
    },
    "CountyPersonalIncomeSummary": {
        "description": "BEA Regional dataset, table CAINC1: annual personal income, population, and per capita personal income for every US county, for the last 10 years.",
        "docs_url": "https://apps.bea.gov/regional/docs/regionalregdata.cfm?param=CAINC1",
        "columns": _REGIONAL_INCOME_COLUMNS,
    },
    "CustomQuery": {
        "description": "Rows returned by the custom BEA GetData query configured on this source (dataset name and parameters chosen by the user).",
        "docs_url": "https://apps.bea.gov/api/_pdf/bea_web_service_api_user_guide.pdf",
    },
}
