"""Canonical, documentation-sourced descriptions for Rapid7 InsightVM endpoints and columns.

Sourced from the Rapid7 InsightVM Cloud Integrations API (v4) reference
(https://help.rapid7.com/insightvm/en-us/api/integrations.html). Keyed by the endpoint names in
`settings.py` `RAPID7_INSIGHTVM_ENDPOINTS`, which match the `ExternalDataSchema.name` of a synced
table. Column coverage is intentionally partial (the v4 objects are deeply nested); anything absent
here falls back to LLM enrichment.
"""

from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "assets": {
        "description": "A scanned asset (host) in InsightVM, with its network identity, operating system, "
        "risk score, tags, and the vulnerability findings detected on it.",
        "docs_url": "https://help.rapid7.com/insightvm/en-us/api/integrations.html",
        "columns": {
            "id": "Unique identifier for the asset.",
            "host_name": "Primary hostname of the asset.",
            "ip": "IP address of the asset.",
            "mac": "MAC address of the asset, when known.",
            "os": "Operating system detected on the asset.",
            "risk_score": "InsightVM risk score for the asset.",
            "tags": "Tags applied to the asset (site, location, owner, or custom tags).",
            "last_scan_time": "Timestamp of the most recent scan of the asset.",
            "vulnerabilities": "Vulnerability findings detected on the asset (status, proof, port, protocol, first/last found).",
        },
    },
    "vulnerabilities": {
        "description": "A unique vulnerability definition in InsightVM, with severity, CVSS scoring, "
        "CVE mappings, exploit and malware-kit indicators, and remediation references.",
        "docs_url": "https://help.rapid7.com/insightvm/en-us/api/integrations.html",
        "columns": {
            "id": "Unique identifier for the vulnerability definition.",
            "title": "Human-readable title of the vulnerability.",
            "description": "Detailed description of the vulnerability.",
            "severity": "Severity classification (e.g. Critical, Severe, Moderate).",
            "cvss_v2_score": "CVSS v2 base score.",
            "cvss_v3_score": "CVSS v3 base score.",
            "cves": "CVE identifiers associated with the vulnerability.",
            "published": "Date the vulnerability was published.",
            "added": "Date the vulnerability was added to InsightVM's content.",
            "exploits": "Known exploits associated with the vulnerability.",
            "malware_kits": "Known malware kits that leverage the vulnerability.",
        },
    },
}
