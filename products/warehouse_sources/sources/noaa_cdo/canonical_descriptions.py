from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.noaa_cdo.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "data": {
        "description": "Weather observations for the selected dataset and station, converted to metric units.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "date": "Date and time of the observation.",
            "station": "Identifier of the station that recorded the observation.",
            "datatype": "Identifier of the observed measurement type.",
            "value": "Observed value, scaled and converted to metric units by NOAA.",
            "attributes": "Additional attributes supplied with the observation.",
        },
    },
    "datasets": {
        "description": "NOAA datasets with observations from the selected station.",
        "docs_url": API_DOCS_URL,
        "columns": {
            "id": "Dataset identifier used when requesting observations.",
            "name": "Dataset name.",
            "mindate": "Earliest date available in the dataset.",
            "maxdate": "Latest date available in the dataset.",
        },
    },
    "stations": {
        "description": "Weather observing stations that support the selected dataset.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Station identifier.", "name": "Station name."},
    },
    "datatypes": {
        "description": "Measurement types available for the selected dataset and station.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Measurement type identifier.", "name": "Measurement type name."},
    },
    "datacategories": {
        "description": "Groups of measurement types available for the selected dataset and station.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Data category identifier.", "name": "Data category name."},
    },
    "locations": {
        "description": "Geographical locations with observations in the selected dataset.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Location identifier.", "name": "Location name."},
    },
    "locationcategories": {
        "description": "Groups of similar locations available for the selected dataset.",
        "docs_url": API_DOCS_URL,
        "columns": {"id": "Location category identifier.", "name": "Location category name."},
    },
}
