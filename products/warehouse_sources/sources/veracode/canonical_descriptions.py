from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "applications": {
        "description": "An application profile in the Veracode portfolio, including its policy-compliance state and scan history.",
        "docs_url": "https://docs.veracode.com/r/c_apps_intro",
        "columns": {
            "guid": "Globally unique identifier for the application profile.",
            "id": "Numeric identifier for the application profile.",
            "oid": "Organization-scoped numeric identifier for the application.",
            "profile": "Application profile details: name, business unit, tags, teams, and custom fields.",
            "scans": "Most recent scan per scan type, each with status and last-modified date.",
            "created": "When the application profile was created.",
            "modified": "When the application profile was last modified.",
            "last_completed_scan_date": "When the most recent scan of any type completed.",
            "app_profile_url": "Deep link to the application profile in the Veracode Platform.",
            "results_url": "Deep link to the application's results in the Veracode Platform.",
        },
    },
    "sandboxes": {
        "description": "A development sandbox belonging to an application, used to scan code before it is promoted to a policy scan.",
        "docs_url": "https://docs.veracode.com/r/c_apps_intro",
        "columns": {
            "guid": "Globally unique identifier for the sandbox.",
            "application_guid": "GUID of the application this sandbox belongs to.",
            "id": "Numeric identifier for the sandbox.",
            "name": "Display name of the sandbox.",
            "owner": "User who created the sandbox.",
            "auto_recreate": "Whether the sandbox is automatically recreated after expiry.",
            "custom_fields": "Custom name/value metadata attached to the sandbox.",
            "created": "When the sandbox was created.",
            "modified": "When the sandbox was last modified.",
        },
    },
    "findings": {
        "description": "Static, dynamic, and manual security findings for an application, with severity, CWE, and remediation status.",
        "docs_url": "https://docs.veracode.com/r/c_findings_v2_intro",
        "columns": {
            "issue_id": "Identifier for the finding, unique within its application.",
            "application_guid": "GUID of the application this finding belongs to.",
            "scan_type": "Scan type that produced the finding (STATIC, DYNAMIC, or MANUAL).",
            "description": "Human-readable description of the finding.",
            "count": "Number of occurrences of this finding.",
            "context_type": "Whether the finding is from the application policy scan or a sandbox.",
            "context_guid": "GUID of the sandbox context, when the finding is a sandbox finding.",
            "violates_policy": "Whether the finding violates the application's assigned policy.",
            "severity": "Severity of the finding on Veracode's 0-5 scale.",
            "finding_status": "Current status of the finding: new/open/closed, resolution, first/last found dates.",
            "finding_details": "Finding specifics such as CWE, file path, line number, and affected component.",
        },
    },
    "sca_findings": {
        "description": "Software Composition Analysis findings for an application: vulnerabilities in open-source and third-party components.",
        "docs_url": "https://docs.veracode.com/r/c_findings_v2_intro",
        "columns": {
            "issue_id": "Identifier for the finding, unique within its application.",
            "application_guid": "GUID of the application this finding belongs to.",
            "scan_type": "Scan type that produced the finding (SCA).",
            "description": "Human-readable description of the finding.",
            "violates_policy": "Whether the finding violates the application's assigned policy.",
            "severity": "Severity of the finding on Veracode's 0-5 scale.",
            "finding_status": "Current status of the finding: new/open/closed, resolution, first/last found dates.",
            "finding_details": "Finding specifics such as the affected component, version, CVE, and CVSS score.",
        },
    },
}
