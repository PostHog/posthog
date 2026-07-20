"""Canonical, documentation-sourced descriptions for SonarQube Cloud endpoints and columns.

Sourced from the official SonarQube Cloud Web API reference (the in-app `/web_api` docs).
Keyed by the endpoint names in `settings.py` `SONAR_CLOUD_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects (top-level components) in the organization, as returned by components/search_projects.",
        "docs_url": "https://sonarcloud.io/web_api/api/components",
        "columns": {
            "key": "Unique project key within the organization.",
            "name": "Display name of the project.",
            "qualifier": "Component qualifier; TRK for projects.",
            "organization": "Organization key the project belongs to.",
            "analysisDate": "Timestamp of the project's most recent analysis.",
            "revision": "SCM revision of the most recent analysis.",
            "visibility": "Project visibility (public or private).",
        },
    },
    "issues": {
        "description": "Code issues (bugs, vulnerabilities, code smells) across the organization's projects.",
        "docs_url": "https://sonarcloud.io/web_api/api/issues",
        "columns": {
            "key": "Unique identifier for the issue.",
            "rule": "Key of the rule that raised the issue.",
            "severity": "Issue severity (INFO, MINOR, MAJOR, CRITICAL, BLOCKER).",
            "component": "Key of the component (file) the issue was found in.",
            "project": "Key of the project the issue belongs to.",
            "line": "Line number the issue points to, if any.",
            "status": "Current status of the issue (e.g. OPEN, CONFIRMED, RESOLVED, CLOSED).",
            "resolution": "Resolution once the issue is closed (e.g. FIXED, WONTFIX, FALSE-POSITIVE).",
            "type": "Issue type (BUG, VULNERABILITY, CODE_SMELL).",
            "effort": "Estimated effort to fix the issue.",
            "tags": "Tags attached to the issue.",
            "creationDate": "Timestamp when the issue was first detected.",
            "updateDate": "Timestamp when the issue was last updated.",
            "author": "Author of the code that introduced the issue.",
        },
    },
    "metrics": {
        "description": "Definitions of the metrics SonarQube Cloud can compute (coverage, bugs, duplications, ...).",
        "docs_url": "https://sonarcloud.io/web_api/api/metrics",
        "columns": {
            "id": "Internal identifier of the metric.",
            "key": "Unique metric key (e.g. coverage, bugs, ncloc).",
            "name": "Human-readable metric name.",
            "description": "Description of what the metric measures.",
            "domain": "Domain the metric belongs to (e.g. Coverage, Reliability).",
            "type": "Value type of the metric (INT, FLOAT, PERCENT, RATING, ...).",
            "direction": "Whether higher or lower values are better.",
            "qualitative": "Whether the metric is qualitative.",
            "hidden": "Whether the metric is hidden from the UI.",
        },
    },
    "quality_gates": {
        "description": "Quality gates defined in the organization (the pass/fail conditions applied to analyses).",
        "docs_url": "https://sonarcloud.io/web_api/api/qualitygates",
        "columns": {
            "id": "Unique identifier of the quality gate.",
            "name": "Name of the quality gate.",
            "isDefault": "Whether this is the organization's default quality gate.",
            "isBuiltIn": "Whether this is a built-in, non-editable quality gate.",
        },
    },
}
