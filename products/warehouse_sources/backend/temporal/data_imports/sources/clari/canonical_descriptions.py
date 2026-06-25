"""Canonical, documentation-sourced descriptions for Clari endpoints and columns.

Sourced from the official Clari REST API reference (https://developer.clari.com/). Keyed by the
endpoint names in `settings.py` `ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
Clari table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "audit_events": {
        "description": "An audit log of user and system actions taken in Clari, such as forecast edits and submissions.",
        "docs_url": "https://developer.clari.com/",
        "columns": {
            "eventId": "Unique identifier for the audit event.",
            "eventType": "Type of action recorded (e.g. forecast update, submission).",
            "eventTimestamp": "Time at which the action occurred.",
            "userId": "Identifier of the user who performed the action.",
            "userEmail": "Email address of the user who performed the action.",
            "fieldName": "Name of the forecast field that was changed, if applicable.",
            "oldValue": "Previous value of the changed field, if applicable.",
            "newValue": "New value of the changed field, if applicable.",
            "timeFrame": "Forecast period (e.g. quarter) the event applies to.",
        },
    },
    "forecast": {
        "description": "A snapshot of forecast values for a quarter, broken down by user, period, and forecast category.",
        "docs_url": "https://developer.clari.com/",
        "columns": {
            "userId": "Identifier of the user the forecast row belongs to.",
            "userName": "Display name of the user the forecast row belongs to.",
            "userEmail": "Email address of the user the forecast row belongs to.",
            "fieldName": "Name of the forecast field (e.g. commit, best case, pipeline).",
            "value": "Numeric forecast value for the field.",
            "currency": "Currency code the forecast value is denominated in.",
            "timeFrame": "Forecast period (e.g. quarter) the value applies to.",
            "timePeriodId": "Identifier of the time period the forecast covers.",
            "updatedTime": "Time at which the forecast value was last updated.",
        },
    },
}
