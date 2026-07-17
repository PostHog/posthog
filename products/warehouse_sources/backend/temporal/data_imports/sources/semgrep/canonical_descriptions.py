# Descriptions sourced from the official Semgrep API reference (https://semgrep.dev/api/v1/docs/)
# and its published OpenAPI spec (https://semgrep.dev/api/v1/public_v1.openapi.yaml).
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_FAN_OUT_COLUMNS = {
    "deployment_id": "Unique numerical identifier of the Semgrep deployment this row belongs to (added by PostHog).",
    "deployment_slug": "Machine-readable slug of the Semgrep deployment this row belongs to (added by PostHog).",
}

_SHARED_FINDING_COLUMNS = {
    "id": "Unique ID of this finding.",
    "ref": "External reference to the source of this finding (e.g. a branch or pull request ref).",
    "first_seen_scan_id": "Unique ID of the Semgrep scan that first identified this finding.",
    "match_based_id": "ID calculated from the finding's file path, rule identifier and pattern, and index.",
    "syntactic_id": "ID calculated from the finding's file path, rule and matched code content.",
    "created_at": "The timestamp when this finding was created.",
    "relevant_since": "The timestamp when this finding was detected by Semgrep (the first time, or when reintroduced).",
    "rule_name": "Name of the rule that triggered the finding (deprecated in favor of rule.name).",
    "rule_message": "Rule message at the time of finding identification (deprecated in favor of rule.message).",
    "rule": "Details of the rule that triggered this finding (name, message, category, confidence, severity, CWE and OWASP names).",
    "location": "File path, line and column range where the finding was detected.",
    "line_of_code_url": "The source URL including file and line number.",
    "repository": "Repository where the finding was detected (name and URL).",
    "severity": "Severity of the finding, derived from the rule that triggered it: low, medium, high, or critical.",
    "confidence": "Confidence of the finding, derived from the rule that triggered it: low, medium, or high.",
    "categories": "The categories of the finding as classified by the associated rule metadata.",
    "state": "The finding's resolution state, managed only by changes detected at scan time: fixed, muted, or unresolved.",
    "state_updated_at": "When this finding's resolution state was last updated, as distinct from when it was triaged.",
    "status": "The finding's status as exposed in the Semgrep UI, combining `state` and `triage_state`: open, reviewing, fixing, fixed, ignored, or provisionally_ignored.",
    "triage_state": "The finding's triage state, managed by user triage actions: untriaged, reviewing, fixing, ignored, or provisionally_ignored.",
    "triage_reason": "Why the finding was triaged (e.g. acceptable_risk, false_positive, no_time).",
    "triage_comment": "Free-form comment left when the finding was triaged.",
    "triaged_at": "When the finding was last triaged.",
    "external_ticket": "Reference to the external ticket (e.g. Jira) linked to this finding, if any.",
    "review_comments": "External review comment information associated with the finding.",
    **_FAN_OUT_COLUMNS,
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "deployments": {
        "description": "The Semgrep deployment (organization) the API token can access, with its identifiers and links to related resources.",
        "docs_url": "https://semgrep.dev/api/v1/docs/#tag/DeploymentsService",
        "columns": {
            "id": "Unique numerical identifier of the deployment.",
            "name": "Human readable name of the deployment.",
            "slug": "Sanitized machine-readable name, used as the primary identifier through the web API.",
            "findings": "Link to the deployment's findings resource on the API.",
        },
    },
    "projects": {
        "description": "Projects (repositories) that have been scanned by or onboarded to Semgrep in the deployment. Archived repositories are not returned.",
        "docs_url": "https://semgrep.dev/api/v1/docs/#tag/ProjectsService",
        "columns": {
            "id": "Unique ID of this project.",
            "name": "Name of the project, e.g. `myorg/myrepo`.",
            "url": "URL of the project, if there is one.",
            "tags": "Tags associated to this project.",
            "created_at": "Time when this project was created.",
            "latest_scan_at": "Time of the latest Semgrep scan, if there is one.",
            "primary_branch": "The primary branch of the project, if known.",
            "default_branch": "The default branch in the source code manager.",
            "managed_scan_config": "Semgrep Managed Scans configuration for the project, if enabled.",
            **_FAN_OUT_COLUMNS,
        },
    },
    "sast_findings": {
        "description": "Code (SAST) findings Semgrep has identified in the deployment, deduplicated across refs/branches to match the counts in the Semgrep UI.",
        "docs_url": "https://semgrep.dev/api/v1/docs/#tag/FindingsService",
        "columns": {
            **_SHARED_FINDING_COLUMNS,
            "assistant": "Semgrep Assistant data (autofix, autotriage, component tags, guidance). Only present if Assistant is enabled.",
            "sourcing_policy": "Reference to the policy that generated this finding, with some basic information.",
            "click_to_fix_prs": "Pull requests created by Semgrep's autofix feature (Click to Fix) for this finding.",
            "click_to_fix_failures": "Failed PR creation attempts by Semgrep's autofix feature (Click to Fix) for this finding.",
        },
    },
    "sca_findings": {
        "description": "Supply chain (SCA) findings Semgrep has identified in the deployment's dependencies, deduplicated across refs/branches to match the counts in the Semgrep UI.",
        "docs_url": "https://semgrep.dev/api/v1/docs/#tag/FindingsService",
        "columns": {
            **_SHARED_FINDING_COLUMNS,
            "vulnerability_identifier": "CVE or GHSA identifier of the vulnerability the finding is based on.",
            "found_dependency": "The dependency (package, version, ecosystem, transitivity, lockfile) in which the finding was identified.",
            "usage": "How the vulnerable code is used, e.g. whether the vulnerable function is reachable from first-party code.",
            "reachability": "Reachability of the vulnerability: reachable, always_reachable, conditionally_reachable, unreachable, or unknown.",
            "reachable_condition": "Condition under which the vulnerability is reachable, if any.",
            "epss_score": "EPSS (Exploit Prediction Scoring System) score and percentile for the vulnerability.",
            "fix_recommendations": "Recommended dependency upgrades that fix the finding.",
            "is_malicious": "Whether the finding comes from a known-malicious dependency.",
        },
    },
    "secrets": {
        "description": "Secrets findings Semgrep has detected in the deployment's repositories, with validation state for supported services. Note: this endpoint returns camelCase field names.",
        "docs_url": "https://semgrep.dev/api/v1/docs/#tag/SecretsService",
        "columns": {
            "id": "ID of the finding.",
            "type": "Service type for the secrets finding (e.g. AWS, GitHub, GitLab).",
            "mode": "The behavior of the finding reporting: MODE_MONITOR, MODE_COMMENT, MODE_BLOCK, or MODE_DISABLED.",
            "status": "Status of the finding: FINDING_STATUS_OPEN, FINDING_STATUS_IGNORED, FINDING_STATUS_FIXED, FINDING_STATUS_REMOVED, or FINDING_STATUS_UNKNOWN.",
            "severity": "Severity of the finding: SEVERITY_LOW, SEVERITY_MEDIUM, SEVERITY_HIGH, or SEVERITY_CRITICAL.",
            "confidence": "Confidence of the finding: CONFIDENCE_LOW, CONFIDENCE_MEDIUM, or CONFIDENCE_HIGH.",
            "validationState": "Whether the secret was validated against its service: confirmed valid, confirmed invalid, validation error, or no validator.",
            "findingPath": "File path where the finding was detected.",
            "findingPathUrl": "URL to the file where the finding was detected.",
            "ref": "Branch where the finding was detected.",
            "refUrl": "URL to the branch where the finding was detected.",
            "repository": "Repository where the finding was detected (name, URL, SCM type, visibility).",
            "ruleHashId": "ID of the rule that triggered the finding.",
            "createdAt": "Creation timestamp.",
            "updatedAt": "Update timestamp.",
            "reviewComments": "External review comment information associated with the finding.",
            "externalTicket": "Reference to the external ticket linked to this finding, if any.",
            **_FAN_OUT_COLUMNS,
        },
    },
}
