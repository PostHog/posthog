"""Canonical, documentation-sourced descriptions for SonarQube Server endpoints and columns.

Sourced from the official SonarQube Web API reference (`<your-instance>/web_api`). Keyed by the
endpoint names in `settings.py` `SONARQUBE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced SonarQube table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "projects": {
        "description": "Projects analyzed on your SonarQube instance (components with the TRK qualifier).",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/",
        "columns": {
            "key": "Unique project key.",
            "name": "Display name of the project.",
            "qualifier": "Component qualifier; TRK for projects.",
            "visibility": "Whether the project is public or private.",
            "lastAnalysisDate": "Timestamp of the most recent analysis.",
        },
    },
    "metrics": {
        "description": "Definitions of the metrics SonarQube can measure (e.g. coverage, bugs, code smells).",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/metric-definitions/",
        "columns": {
            "key": "Unique metric key (e.g. `coverage`, `bugs`).",
            "name": "Human-readable metric name.",
            "type": "Value type of the metric (INT, FLOAT, PERCENT, RATING, …).",
            "domain": "Domain the metric belongs to (Reliability, Coverage, …).",
            "description": "Explanation of what the metric measures.",
            "direction": "Whether higher (1) or lower (-1) values are better.",
            "qualitative": "Whether the metric feeds a quality rating.",
            "hidden": "Whether the metric is hidden from the UI.",
        },
    },
    "rules": {
        "description": "The catalog of coding rules used to raise issues during analysis.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/rules/overview/",
        "columns": {
            "key": "Unique rule key (e.g. `java:S1234`).",
            "name": "Human-readable rule name.",
            "lang": "Language the rule applies to.",
            "langName": "Display name of the language.",
            "type": "Rule type: BUG, VULNERABILITY, CODE_SMELL, or SECURITY_HOTSPOT.",
            "severity": "Default severity assigned to issues raised by the rule.",
            "status": "Rule lifecycle status (READY, DEPRECATED, …).",
        },
    },
    "issues": {
        "description": "Issues raised by analysis — bugs, vulnerabilities, code smells, and security hotspots.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/issues/",
        "columns": {
            "key": "Unique issue key.",
            "rule": "Key of the rule that raised the issue.",
            "severity": "Issue severity (BLOCKER, CRITICAL, MAJOR, MINOR, INFO).",
            "component": "Key of the file or component the issue is on.",
            "project": "Key of the project the issue belongs to.",
            "line": "Line number the issue points at.",
            "status": "Issue status (OPEN, CONFIRMED, RESOLVED, CLOSED, …).",
            "resolution": "Resolution when the issue is closed (FIXED, WONTFIX, FALSE-POSITIVE).",
            "type": "Issue type: BUG, VULNERABILITY, CODE_SMELL.",
            "message": "Description of the issue.",
            "effort": "Estimated effort to fix the issue.",
            "author": "Email of the author of the code that raised the issue.",
            "creationDate": "Time at which the issue was first detected.",
            "updateDate": "Time at which the issue was last changed.",
        },
    },
    "users": {
        "description": "Users of the SonarQube instance. Requires the Administer System permission.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/instance-administration/authentication/overview/",
        "columns": {
            "login": "Unique user login.",
            "name": "Display name of the user.",
            "email": "User's email address.",
            "active": "Whether the user account is active.",
            "local": "Whether the user is managed locally rather than via an external identity provider.",
        },
    },
}
