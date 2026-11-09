"""Canonical, documentation-sourced descriptions for SonarQube Cloud endpoints and columns.

Sourced from the official SonarQube Cloud Web API reference (the in-app `/web_api` docs).
Keyed by the endpoint names in `settings.py` `SONAR_CLOUD_ENDPOINTS`, which match the
`ExternalDataSchema.name` of a synced table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "rules": {
        "description": "Coding rules available to the organization, which resolve the rule keys on issues.",
        "docs_url": "https://sonarcloud.io/web_api/api/rules",
        "columns": {
            "key": "Unique rule key, in the form <repository>:<rule>.",
            "repo": "Key of the rule repository.",
            "name": "Name of the rule.",
            "createdAt": "Timestamp when the rule was created.",
            "severity": "Default severity of the rule.",
            "status": "Status of the rule (BETA, DEPRECATED, READY, REMOVED).",
            "lang": "Key of the language the rule applies to.",
            "langName": "Name of the language the rule applies to.",
            "type": "Rule type (CODE_SMELL, BUG, VULNERABILITY, SECURITY_HOTSPOT).",
            "remFnBaseEffort": "Base remediation effort for an issue raised by the rule.",
            "impacts": "Software qualities the rule affects, with a severity for each.",
            "isTemplate": "Whether the rule is a template for custom rules.",
        },
    },
    "measures": {
        "description": "Current metric values per component (project, directory, or file), one row per component and metric, from measures/component_tree.",
        "docs_url": "https://sonarcloud.io/web_api/api/measures",
        "columns": {
            "project_key": "Key of the project the component belongs to.",
            "key": "Key of the component. Equals project_key for the project-level row.",
            "name": "Name of the component.",
            "qualifier": "Component qualifier: TRK for the project, DIR for a directory, FIL for a file, UTS for a test file.",
            "path": "Path of the component in the project.",
            "language": "Language of the file, for file components.",
            "metric": "Key of the metric (e.g. coverage, ncloc, bugs).",
            "value": "Value of the metric for the component.",
            "bestValue": "Whether the value is the best value the metric can have.",
        },
    },
    "measures_history": {
        "description": "Metric values per project over time, one row per project, metric, and analysis, from measures/search_history.",
        "docs_url": "https://sonarcloud.io/web_api/api/measures",
        "columns": {
            "project_key": "Key of the project.",
            "metric": "Key of the metric (e.g. coverage, ncloc, bugs).",
            "date": "Timestamp of the analysis that computed the value.",
            "value": "Value of the metric at that analysis. Empty when the analysis did not compute the metric.",
        },
    },
    "issue_changelog": {
        "description": "Change history of each issue (status, assignee, severity, and other field changes), from issues/changelog.",
        "docs_url": "https://sonarcloud.io/web_api/api/issues",
        "columns": {
            "issue_key": "Key of the issue the change applies to.",
            "project_key": "Key of the project the issue belongs to.",
            "creationDate": "Timestamp of the change.",
            "user": "Login of the user who made the change. Empty for automatic changes.",
            "userName": "Name of the user who made the change.",
            "diffs": "Fields the change modified, each with its key, old value, and new value.",
        },
    },
}
