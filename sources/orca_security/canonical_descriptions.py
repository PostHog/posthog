from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

# Column names match the Serving Layer field names lifted to the row root by `_normalize_item`.
# Coverage is intentionally partial — fields not listed fall back to LLM enrichment.
CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "alerts": {
        "description": "Security alerts Orca raised for detected risks (misconfigurations, malicious activity, neglected assets, and more).",
        "docs_url": "https://docs.orcasecurity.io/docs/alerts",
        "columns": {
            "id": "Globally unique identifier for the alert record.",
            "AlertId": "Orca's identifier for the alert.",
            "AlertType": "Human-readable name of the rule that produced the alert.",
            "Category": "Risk category the alert belongs to (e.g. IAM misconfigurations, Data at risk).",
            "RiskLevel": "Severity of the alert (e.g. informational, low, medium, high, critical).",
            "OrcaScore": "Orca's contextual risk score for the alert.",
            "Status": "Current alert status (e.g. open, in progress, dismissed).",
            "Source": "System or scan that surfaced the alert.",
            "RuleSource": "Origin of the rule (e.g. Orca, Vendor).",
            "Labels": "Tags associated with the alert.",
            "CreatedAt": "Timestamp when the alert was first created.",
            "LastSeen": "Timestamp when the alert was most recently observed.",
        },
    },
    "assets": {
        "description": "Cloud asset inventory discovered by Orca (compute instances, storage, functions, databases, and more).",
        "docs_url": "https://docs.orcasecurity.io/docs/asset-inventory",
        "columns": {
            "id": "Globally unique identifier for the asset record.",
            "Name": "Display name of the asset.",
            "Type": "Asset type (e.g. AwsEc2Instance, AwsS3Bucket).",
            "CloudProvider": "Cloud provider hosting the asset (e.g. aws, azure, gcp).",
        },
    },
    "cloud_accounts": {
        "description": "Cloud accounts, subscriptions, or projects connected to Orca for scanning.",
        "docs_url": "https://docs.orcasecurity.io/docs/cloud-accounts",
        "columns": {
            "id": "Globally unique identifier for the cloud account record.",
            "Name": "Display name of the cloud account.",
            "CloudProvider": "Cloud provider of the account (e.g. aws, azure, gcp).",
        },
    },
    "vulnerabilities": {
        "description": "CVEs and vulnerabilities Orca detected across scanned assets.",
        "docs_url": "https://docs.orcasecurity.io/docs/vulnerabilities",
        "columns": {
            "id": "Globally unique identifier for the vulnerability record.",
            "CVEID": "CVE identifier for the vulnerability.",
            "Severity": "Severity classification of the vulnerability.",
        },
    },
}
