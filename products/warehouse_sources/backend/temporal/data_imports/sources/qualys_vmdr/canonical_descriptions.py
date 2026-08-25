from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS_URL = "https://docs.qualys.com/en/vm/api/index.htm"

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "hosts": {
        "description": "Asset inventory: one row per host in the Qualys subscription, with tracking method, OS, and last-scan timestamps.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "id": "Unique Qualys host ID.",
            "ip": "IP address of the host.",
            "tracking_method": "How the host is tracked in Qualys (IP, DNS, NETBIOS, or agent).",
            "dns": "DNS hostname of the host.",
            "netbios": "NetBIOS name of the host.",
            "os": "Operating system detected on the host.",
            "last_vuln_scan_datetime": "When the host was last scanned by a VM scan.",
            "last_vm_scanned_date": "When the host was last successfully scanned for vulnerabilities.",
        },
    },
    "host_list_detection": {
        "description": "Per-host vulnerability detections: one row per (host, detection) with status, severity, and first/last found timestamps — the core VMDR remediation feed.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "unique_vuln_id": "Subscription-wide unique ID of the detection record.",
            "qid": "Qualys ID of the vulnerability (joins to the knowledge_base table).",
            "type": "Detection type: Confirmed, Potential, or Info.",
            "severity": "Severity level of the detection (1-5).",
            "status": "Detection status: New, Active, Fixed, or Re-Opened.",
            "port": "Port the vulnerability was detected on, if applicable.",
            "protocol": "Protocol the vulnerability was detected over, if applicable.",
            "results": "Scan test results/evidence for the detection.",
            "first_found_datetime": "When the vulnerability was first detected on the host.",
            "last_found_datetime": "When the vulnerability was most recently detected on the host.",
            "last_update_datetime": "When the detection record was last updated.",
            "times_found": "Number of times the vulnerability has been detected on the host.",
            "qds": "Qualys Detection Score (0-100) for the detection.",
            "host_id": "Unique Qualys host ID the detection belongs to (joins to the hosts table).",
            "host_ip": "IP address of the host the detection belongs to.",
        },
    },
    "scans": {
        "description": "VM scan history: one row per vulnerability scan with launch time, state, and target.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "ref": "Unique scan reference (for example scan/1234567890.12345).",
            "type": "How the scan was launched (On-Demand, Scheduled, or API).",
            "title": "Title of the scan.",
            "user_login": "Qualys user who launched the scan.",
            "launch_datetime": "When the scan was launched.",
            "duration": "How long the scan ran.",
            "state": "Scan state (for example Finished, Running, Canceled, or Error).",
            "target": "IPs/ranges the scan targeted.",
            "processed": "Whether the scan results have been processed (1) or not (0).",
        },
    },
    "knowledge_base": {
        "description": "Qualys KnowledgeBase: one row per vulnerability definition (QID) with severity, category, and CVE references.",
        "docs_url": _API_DOCS_URL,
        "columns": {
            "qid": "Qualys ID of the vulnerability definition.",
            "vuln_type": "Vulnerability type: Vulnerability, Potential Vulnerability, or Information Gathered.",
            "severity_level": "Severity level assigned by Qualys (1-5).",
            "title": "Title of the vulnerability.",
            "category": "Vulnerability category (for example Web server, Windows, or Database).",
            "cve_list": "CVE identifiers associated with the vulnerability (JSON).",
            "patchable": "Whether a patch is available for the vulnerability.",
            "published_datetime": "When the vulnerability definition was first published.",
            "last_service_modification_datetime": "When Qualys last modified the vulnerability definition.",
        },
    },
}
