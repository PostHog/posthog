"""Canonical, documentation-sourced descriptions for CIMIS endpoints and columns.

Sourced from the official CIMIS Web API reference (https://et.water.ca.gov/Rest/Index). Keyed by the
endpoint names in `settings.py` `CIMIS_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
CIMIS table. Columns absent here fall back to LLM enrichment. The weather-data tables flatten each nested
measurement object into `<Item>_Value`, `<Item>_Qc`, and `<Item>_Unit` columns, so only the shared
identity columns are described here; the per-measurement columns fall back to the LLM.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DATA_DOCS_URL = "https://et.water.ca.gov/Rest/Index"

_DATA_IDENTITY_COLUMNS = {
    "Date": "Calendar date of the observation (yyyy-mm-dd).",
    "Julian": "Day of the year (1-366) for the observation date.",
    "Station": "CIMIS station number the observation came from.",
    "Standard": "Unit system the values are reported in (english or metric).",
    "ZipCodes": "Zip codes served by the station for this record.",
    "Scope": "Granularity of the record (daily or hourly).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "stations": {
        "description": "Metadata for every CIMIS weather station, including location, elevation, and active status.",
        "docs_url": "https://et.water.ca.gov/Rest/Index",
        "columns": {
            "StationNbr": "Unique CIMIS station number.",
            "Name": "Station name.",
            "City": "City the station is located in.",
            "RegionalOffice": "CIMIS regional office responsible for the station.",
            "County": "County the station is located in.",
            "ConnectDate": "Date the station was connected to the network.",
            "DisconnectDate": "Date the station was disconnected (a far-future date if still active).",
            "IsActive": "Whether the station is currently active.",
            "IsEtoStation": "Whether the station reports reference evapotranspiration (ETo).",
            "Elevation": "Station elevation.",
            "GroundCover": "Ground cover at the station (e.g. grass).",
            "HmsLatitude": "Station latitude in degrees-minutes-seconds and decimal form.",
            "HmsLongitude": "Station longitude in degrees-minutes-seconds and decimal form.",
            "ZipCodes": "Zip codes served by the station.",
            "SitingDesc": "Description of the station siting.",
        },
    },
    "station_zipcodes": {
        "description": "Mapping of zip codes to the CIMIS Weather Station Network station that serves them.",
        "docs_url": "https://et.water.ca.gov/Rest/Index",
        "columns": {
            "StationNbr": "CIMIS station number serving the zip code.",
            "ZipCode": "Zip code served by the station.",
            "ConnectDate": "Date the zip code was associated with the station.",
            "DisconnectDate": "Date the association ended (a far-future date if still active).",
            "IsActive": "Whether the association is currently active.",
        },
    },
    "spatial_zipcodes": {
        "description": "Zip codes supported by the Spatial CIMIS System (2km gridded interpolated data).",
        "docs_url": "https://et.water.ca.gov/Rest/Index",
        "columns": {
            "ZipCode": "Supported zip code.",
            "ConnectDate": "Date the zip code became available in the spatial system.",
            "DisconnectDate": "Date the zip code support ended (a far-future date if still active).",
            "IsActive": "Whether the zip code is currently supported.",
        },
    },
    "daily_data": {
        "description": "Daily weather and reference evapotranspiration (ETo) observations per station.",
        "docs_url": _DATA_DOCS_URL,
        "columns": _DATA_IDENTITY_COLUMNS,
    },
    "hourly_data": {
        "description": "Hourly weather and reference evapotranspiration (ETo) observations per station.",
        "docs_url": _DATA_DOCS_URL,
        "columns": {
            **_DATA_IDENTITY_COLUMNS,
            "Hour": "Hour of the observation in HHMM form (e.g. 100 = 01:00).",
        },
    },
}
