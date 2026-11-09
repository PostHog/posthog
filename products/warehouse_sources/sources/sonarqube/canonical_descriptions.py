"""Canonical, documentation-sourced descriptions for SonarQube Server endpoints and columns.

Sourced from the official SonarQube Web API reference (`<your-instance>/web_api`). Keyed by the
endpoint names in `settings.py` `SONARQUBE_ENDPOINTS`, which match the `ExternalDataSchema.name` of a
synced SonarQube table. Columns absent here fall back to LLM enrichment.
"""

from products.warehouse_sources.sources.sdk import CanonicalDescriptions

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
    "quality_gates": {
        "description": "Quality gates defined on the instance: the sets of conditions a project must meet to pass.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/quality-standards-administration/managing-quality-gates/introduction-to-quality-gates/",
        "columns": {
            "name": "Unique name of the quality gate.",
            "isDefault": "Whether the gate applies to projects that have no gate assigned.",
            "isBuiltIn": "Whether the gate ships with SonarQube and cannot be edited.",
            "caycStatus": "Whether the gate follows the Clean as You Code methodology (compliant, non-compliant, over-compliant).",
        },
    },
    "project_quality_gate_status": {
        "description": "Current quality gate result of each project's main branch, with the result of each condition.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/quality-standards-administration/managing-quality-gates/introduction-to-quality-gates/",
        "columns": {
            "projectKey": "Key of the project.",
            "status": "Quality gate result of the latest analysis: OK, ERROR, or NONE when no gate applies.",
            "conditions": "Each gate condition with its metric, comparator, threshold, actual value, and status.",
            "ignoredConditions": "Whether some conditions were ignored because too few lines changed.",
            "caycStatus": "Whether the applied gate follows the Clean as You Code methodology.",
            "period": "New code period the new-code conditions were evaluated against.",
        },
    },
    "hotspots": {
        "description": "Security hotspots: security-sensitive code that needs a manual review. Deprecated in SonarQube 2026.4 in favor of security issues.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/security-hotspots/",
        "columns": {
            "key": "Unique hotspot key.",
            "component": "Key of the file the hotspot is on.",
            "project": "Key of the project the hotspot belongs to.",
            "securityCategory": "Security category of the hotspot (e.g. sql-injection, weak-cryptography).",
            "vulnerabilityProbability": "Likelihood that the hotspot is a real vulnerability (HIGH, MEDIUM, LOW).",
            "status": "Review status: TO_REVIEW or REVIEWED.",
            "resolution": "Review outcome when reviewed: FIXED, SAFE, or ACKNOWLEDGED.",
            "line": "Line number the hotspot points at.",
            "message": "Description of the hotspot.",
            "assignee": "User the hotspot is assigned to.",
            "author": "Author of the code that raised the hotspot.",
            "ruleKey": "Key of the rule that raised the hotspot.",
            "creationDate": "Time at which the hotspot was first detected.",
            "updateDate": "Time at which the hotspot was last changed.",
        },
    },
    "component_measures": {
        "description": "Current value of each metric on each component (project, directory, file) of each project's main branch, one row per component and metric.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/code-metrics/metrics-definition/",
        "columns": {
            "project": "Key of the project the component belongs to.",
            "component": "Key of the component the value is for.",
            "componentName": "Display name of the component.",
            "qualifier": "Component type: TRK (project), DIR (directory), FIL (file), or UTS (test file).",
            "path": "Path of the component within the project.",
            "language": "Language of the file.",
            "metric": "Key of the metric, matching the `key` of the metrics table.",
            "value": "Value of the metric over the whole code.",
            "bestValue": "Whether the value is the best value the metric can have.",
            "periodValue": "Value of a new-code metric over the new code period.",
        },
    },
    "measures_history": {
        "description": "Value of each metric at each analysis of each project's main branch, one row per project, metric, and analysis date.",
        "docs_url": "https://docs.sonarsource.com/sonarqube-server/latest/user-guide/code-metrics/metrics-definition/",
        "columns": {
            "project": "Key of the project.",
            "metric": "Key of the metric, matching the `key` of the metrics table.",
            "date": "Date of the analysis that computed the value.",
            "value": "Value of the metric at that analysis.",
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
