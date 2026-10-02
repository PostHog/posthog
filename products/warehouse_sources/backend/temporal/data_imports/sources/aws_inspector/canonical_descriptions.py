from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "findings": {
        "description": "Amazon Inspector findings for vulnerabilities and network reachability.",
        "docs_url": "https://docs.aws.amazon.com/inspector/v2/APIReference/API_Finding.html",
        "columns": {
            "finding_arn": "ARN that identifies the finding.",
            "aws_account_id": "AWS account that owns the affected resource.",
            "type": "Type of finding, such as a package vulnerability.",
            "title": "Short title of the finding.",
            "description": "Description of the finding.",
            "severity": "Severity assigned to the finding.",
            "status": "Finding status: active, suppressed, or closed.",
            "first_observed_at": "Time when Inspector first detected the finding.",
            "last_observed_at": "Time when Inspector last detected the finding.",
            "updated_at": "Time when Inspector last updated the finding.",
            "resources": "Resources affected by the finding.",
            "remediation": "Recommendations to correct the finding.",
            "package_vulnerability_details": "Package vulnerability details, including affected packages and vulnerability identifiers.",
            "network_reachability_details": "Network paths and ports associated with the finding.",
            "code_vulnerability_details": "Code vulnerability details associated with the finding.",
            "inspector_score": "Risk score calculated by Amazon Inspector.",
            "fix_available": "Whether a fix is available for the vulnerability.",
            "exploit_available": "Whether a known exploit exists for the vulnerability.",
            "epss": "Probability score for exploitation of the vulnerability.",
            "region": "AWS region selected for this source.",
        },
    },
    "coverage": {
        "description": "Resources monitored by Inspector, with one row for each resource and scan type.",
        "docs_url": "https://docs.aws.amazon.com/inspector/v2/APIReference/API_CoveredResource.html",
        "columns": {
            "account_id": "AWS account that owns the resource.",
            "resource_id": "Identifier of the monitored resource.",
            "resource_type": "Type of monitored resource.",
            "scan_type": "Type of scan applied to the resource.",
            "scan_status": "Scan status and the reason for that status.",
            "scan_mode": "Scanning method used for the resource.",
            "last_scanned_at": "Time when Inspector last scanned the resource.",
            "resource_metadata": "Details specific to the resource type.",
            "region": "AWS region selected for this source.",
        },
    },
    "coverage_statistics": {
        "description": "Counts of resources monitored by Inspector, grouped by resource type.",
        "docs_url": "https://docs.aws.amazon.com/inspector/v2/APIReference/API_ListCoverageStatistics.html",
        "columns": {
            "group_key": "Resource type used to group the count.",
            "count": "Number of resources in the group.",
            "region": "AWS region selected for this source.",
        },
    },
}
