from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.settings import API_DOCS_URL

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "datasets": {
        "description": "Datasets visible to the API key owner, with check coverage and the latest quality status.",
        "docs_url": f"{API_DOCS_URL}/datasets",
        "columns": {
            "id": "Unique dataset identifier.",
            "name": "Dataset name.",
            "lastUpdated": "Time when the dataset was last updated.",
            "checks": "Number of active checks on the dataset.",
            "incidents": "Number of incidents associated with the dataset.",
            "healthStatus": "Percentage of active checks whose latest result passed. Datasets without checks report 100.",
            "dataQualityStatus": "Worst latest result across active checks. Datasets without checks also report pass.",
        },
    },
    "checks": {
        "description": "Checks with their latest evaluation, associated datasets, and linked incidents.",
        "docs_url": f"{API_DOCS_URL}/checks",
        "columns": {
            "id": "Unique check identifier.",
            "name": "Check name.",
            "createdAt": "Time when the check was created.",
            "evaluationStatus": "Latest check status: pass, warn, fail, notEvaluated, or excluded.",
            "definition": "Check definition.",
            "datasets": "Datasets associated with the check.",
            "lastCheckResultValue": "Values and diagnostics from the latest check result.",
        },
    },
    "incidents": {
        "description": "Data quality incidents with their status, severity, linked checks, and assigned lead.",
        "docs_url": f"{API_DOCS_URL}/incidents",
        "columns": {
            "id": "Unique incident identifier.",
            "number": "Incident number shown in Soda Cloud.",
            "title": "Incident title.",
            "status": "Incident status: reported, investigating, fixing, or resolved.",
            "severity": "Incident severity: minor, major, or critical.",
            "created": "Time when the incident was created.",
            "lastUpdated": "Time when the incident was last updated.",
            "checks": "Checks linked to the incident, including their datasets and associated results.",
        },
    },
}
