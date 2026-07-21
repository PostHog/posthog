from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ACS_COLUMNS = {
    "NAME": "Human-readable name of the geography (e.g. state or county name).",
    "B01001_001E": "Estimated total population.",
    "B01002_001E": "Estimated median age of the population.",
    "B19013_001E": "Estimated median household income in the past 12 months (inflation-adjusted dollars).",
    "B19301_001E": "Estimated per capita income in the past 12 months (inflation-adjusted dollars).",
    "B25077_001E": "Estimated median value of owner-occupied housing units (dollars).",
    "B23025_003E": "Estimated civilian labor force (population 16 years and over).",
    "B23025_005E": "Estimated unemployed civilian labor force (population 16 years and over).",
    "B15003_022E": "Estimated population 25 years and over whose highest attainment is a bachelor's degree.",
    "state": "Two-digit state FIPS code.",
}

_DECENNIAL_COLUMNS = {
    "NAME": "Human-readable name of the geography (e.g. state or county name).",
    "P1_001N": "Total population count.",
    "H1_001N": "Total count of housing units.",
    "state": "Two-digit state FIPS code.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "AcsDemographicsByState": {
        "description": "American Community Survey 5-year demographic, income, housing, employment, and education estimates for every US state.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/acs-5year.html",
        "columns": _ACS_COLUMNS,
    },
    "AcsDemographicsByCounty": {
        "description": "American Community Survey 5-year demographic, income, housing, employment, and education estimates for every US county.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/acs-5year.html",
        "columns": {
            **_ACS_COLUMNS,
            "county": "Three-digit county FIPS code, unique within its state.",
        },
    },
    "DecennialPopulationByState": {
        "description": "2020 Decennial Census (PL 94-171 redistricting data) population and housing unit counts for every US state.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/decennial-census.html",
        "columns": _DECENNIAL_COLUMNS,
    },
    "DecennialPopulationByCounty": {
        "description": "2020 Decennial Census (PL 94-171 redistricting data) population and housing unit counts for every US county.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/decennial-census.html",
        "columns": {
            **_DECENNIAL_COLUMNS,
            "county": "Three-digit county FIPS code, unique within its state.",
        },
    },
    "CountyBusinessPatternsByState": {
        "description": "County Business Patterns all-sector establishment, employment, and payroll totals for every US state.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/cbp-zbp/cbp-api.html",
        "columns": {
            "NAME": "Human-readable name of the geography (state name).",
            "NAICS2017": "2017 NAICS industry code (00 = total for all sectors).",
            "NAICS2017_LABEL": "Human-readable label for the NAICS industry code.",
            "ESTAB": "Number of establishments.",
            "EMP": "Number of paid employees for the pay period including March 12.",
            "PAYANN": "Annual payroll in thousands of dollars.",
            "state": "Two-digit state FIPS code.",
        },
    },
    "PopulationEstimatesByState": {
        "description": "Population Estimates Program (vintage 2021) resident population and density for every US state.",
        "docs_url": "https://www.census.gov/data/developers/data-sets/popest-popproj/popest.html",
        "columns": {
            "NAME": "Human-readable name of the geography (state name).",
            "POP_2021": "Estimated resident population as of July 1, 2021.",
            "DENSITY_2021": "Estimated population density (persons per square mile) as of July 1, 2021.",
            "state": "Two-digit state FIPS code.",
        },
    },
    "CustomQuery": {
        "description": "Rows returned by the custom Census query configured on this source (dataset, variables, and geography chosen by the user).",
        "docs_url": "https://www.census.gov/data/developers/guidance/api-user-guide.html",
    },
}
