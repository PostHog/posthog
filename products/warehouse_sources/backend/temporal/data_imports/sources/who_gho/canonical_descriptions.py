from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://www.who.int/data/gho/info/gho-odata-api"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "indicators": {
        "description": "Catalog of every health indicator code the Global Health Observatory publishes.",
        "docs_url": _DOCS_URL,
        "columns": {
            "IndicatorCode": "Indicator code, for example WHOSIS_000001. Use this in the source's indicator codes setting.",
            "IndicatorName": "Human readable indicator name.",
            "Language": "Language of the indicator name, for example EN.",
        },
    },
    "dimensions": {
        "description": "Dimensions observations can be disaggregated by, such as country, sex, or age group.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Code": "Dimension code, for example COUNTRY or SEX. Use this to look up rows in dimension_values.",
            "Title": "Human readable dimension name.",
        },
    },
    "dimension_values": {
        "description": "Values for every dimension, such as country codes for the COUNTRY dimension or SEX_MLE / SEX_FMLE for the SEX dimension.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Code": "Value code, referenced by SpatialDim, Dim1, Dim2, and Dim3 on indicator_data rows.",
            "Title": "Human readable name for the value, for example Afghanistan or Male.",
            "Dimension": "Dimension code this value belongs to, matching a row in the dimensions table.",
            "ParentDimension": "Dimension code of the parent grouping, when this value is nested under a broader one.",
            "ParentCode": "Value code of the parent grouping, when this value is nested under a broader one.",
            "ParentTitle": "Human readable name of the parent grouping.",
        },
    },
    "indicator_data": {
        "description": "Observations for every indicator code you configured, one row per country, year, and disaggregation.",
        "docs_url": _DOCS_URL,
        "columns": {
            "Id": "Row identifier, unique within this indicator's own observation set.",
            "IndicatorCode": "Indicator code this observation belongs to, matching a row in the indicators table.",
            "SpatialDimType": "Kind of spatial dimension this observation is reported for, usually COUNTRY.",
            "SpatialDim": "Spatial dimension value code, for example a country code. Look up its name in dimension_values.",
            "ParentLocationCode": "Code of the WHO region the spatial dimension belongs to.",
            "ParentLocation": "Name of the WHO region the spatial dimension belongs to.",
            "TimeDimType": "Kind of time dimension this observation is reported for, usually YEAR.",
            "TimeDim": "Time period as a plain integer, for example a year.",
            "TimeDimensionValue": "Time period as a display string.",
            "TimeDimensionBegin": "Start date of the time period covered by this observation.",
            "TimeDimensionEnd": "End date of the time period covered by this observation.",
            "Dim1Type": "Dimension code for the first disaggregation, when present, such as SEX.",
            "Dim1": "Value code for the first disaggregation. Look up its name in dimension_values.",
            "Dim2Type": "Dimension code for the second disaggregation, when present.",
            "Dim2": "Value code for the second disaggregation.",
            "Dim3Type": "Dimension code for the third disaggregation, when present.",
            "Dim3": "Value code for the third disaggregation.",
            "DataSourceDimType": "Dimension code identifying the underlying data source, when reported.",
            "DataSourceDim": "Value code identifying the underlying data source.",
            "Value": "Display value, sometimes including a confidence interval, for example '48.0 [46.7-49.6]'.",
            "NumericValue": "Observed value as a plain number.",
            "Low": "Lower bound of the confidence interval, when reported.",
            "High": "Upper bound of the confidence interval, when reported.",
            "Comments": "Free text comments on the observation, when present.",
            "Date": "When WHO last refreshed this indicator's whole dataset. Shared by every row for the indicator.",
        },
    },
}
