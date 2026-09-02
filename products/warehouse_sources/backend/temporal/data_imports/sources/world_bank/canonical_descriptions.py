from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://datahelpdesk.worldbank.org/knowledgebase/articles/898581-api-basic-call-structures"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "countries": {
        "description": "Countries and regional aggregates recognized by the World Bank, with their region, income level, lending type, and capital city.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898590-country-api-queries",
        "columns": {
            "id": "ISO 3166-1 alpha-3 country code, or the World Bank's own code for an aggregate.",
            "iso2Code": "ISO 3166-1 alpha-2 country code.",
            "name": "Country or aggregate name.",
            "region": "Geographic region the country belongs to. Aggregates report the region 'Aggregates'.",
            "adminregion": "Administrative region used for World Bank operational reporting. Empty for high income countries and aggregates.",
            "incomeLevel": "World Bank income classification, such as high income or lower middle income.",
            "lendingType": "World Bank lending category, such as IBRD, IDA, blend, or not classified.",
            "capitalCity": "Capital city. Empty for aggregates.",
            "longitude": "Longitude of the capital city, as a string.",
            "latitude": "Latitude of the capital city, as a string.",
        },
    },
    "indicators": {
        "description": "Catalog of every indicator series the API exposes, with its unit, originating database, and topics.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898599-indicator-api-queries",
        "columns": {
            "id": "Indicator code, for example SP.POP.TOTL. Use this in the source's indicator codes setting.",
            "name": "Human readable indicator name.",
            "unit": "Unit of measure. Often empty because the unit is described in the name.",
            "source": "Database the indicator comes from, matching a row in the sources table.",
            "sourceNote": "Long form description of what the indicator measures and how it is calculated.",
            "sourceOrganization": "Organization that compiled the underlying data.",
            "topics": "Subject areas the indicator is filed under, matching rows in the topics table.",
        },
    },
    "sources": {
        "description": "Databases behind the indicator data, such as World Development Indicators or International Debt Statistics.",
        "docs_url": _DOCS_URL,
        "columns": {
            "id": "Source database identifier. Source 2 is World Development Indicators, the API default.",
            "lastupdated": "Date the source database was last refreshed, as YYYY-MM-DD.",
            "name": "Source database name.",
            "code": "Short code for the source database.",
            "description": "Description of the source database. Often empty.",
            "url": "Link to the source database. Often empty.",
            "dataavailability": "Y when the source exposes data through the API.",
            "metadataavailability": "Y when the source exposes metadata through the API.",
            "concepts": "Number of dimensions the source's data is organized by.",
        },
    },
    "topics": {
        "description": "Subject areas indicators are grouped under, such as Health, Education, or Climate Change.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898611-topic-api-queries",
        "columns": {
            "id": "Topic identifier.",
            "value": "Topic name.",
            "sourceNote": "Description of what the topic covers.",
        },
    },
    "regions": {
        "description": "Geographic regions and regional aggregates used to group countries.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898593-region-api-queries",
        "columns": {
            "id": "Numeric region identifier. Empty for aggregate regions, so the code is the stable key.",
            "code": "Region code, for example AFE for Africa Eastern and Southern.",
            "iso2code": "Two character code for the region.",
            "name": "Region name.",
        },
    },
    "income_levels": {
        "description": "World Bank income classifications assigned to countries.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898596-income-level-api-queries",
        "columns": {
            "id": "Income level code, for example HIC for high income.",
            "iso2code": "Two character code for the income level.",
            "value": "Income level name.",
        },
    },
    "lending_types": {
        "description": "World Bank lending categories assigned to countries.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898608-lending-type-api-queries",
        "columns": {
            "id": "Lending type code, for example IBD for IBRD.",
            "iso2code": "Two character code for the lending type.",
            "value": "Lending type name.",
        },
    },
    "indicator_data": {
        "description": "Observations for every configured indicator code, one row per country and period.",
        "docs_url": "https://datahelpdesk.worldbank.org/knowledgebase/articles/898599-indicator-api-queries",
        "columns": {
            "indicator_id": "Indicator code for this observation, lifted out of the nested indicator object.",
            "indicator_name": "Indicator name, lifted out of the nested indicator object.",
            "country_id": "ISO 3166-1 alpha-2 code of the country or aggregate, lifted out of the nested country object.",
            "country_name": "Country or aggregate name, lifted out of the nested country object.",
            "countryiso3code": "ISO 3166-1 alpha-3 code of the country or aggregate.",
            "date": "Period the observation covers: a year (2024), a month (2024M03), or a quarter (2024Q1).",
            "value": "Observed value, or null when the World Bank has no data for that country and period.",
            "unit": "Unit of measure for the observation. Usually empty.",
            "obs_status": "Observation status flag, for example an estimate marker. Usually empty.",
            "decimal": "Number of decimal places the World Bank recommends when displaying the value.",
            "indicator": "Original nested object holding the indicator id and name.",
            "country": "Original nested object holding the country id and name.",
        },
    },
}
