from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Opaque vendor version labels — never parsed or ordered. Only the KnowledgeBase Vulnerability API
# is versioned past 2.0: Qualys is retiring its 2.0 (EOS Dec 2025) in favor of 4.0, which serves the
# same feed at `/api/4.0/fo/knowledge_base/vuln/` but requires JWT Bearer auth instead of basic auth.
# The FO Host List / Host List Detection / VM Scan APIs are a separate versioning track and stay on
# `/api/2.0/` with basic auth under both source-level pins.
QUALYS_VMDR_API_VERSION_2_0 = "2.0"
QUALYS_VMDR_API_VERSION_4_0 = "4.0"
# Declared oldest -> newest; the default is always the last entry.
QUALYS_VMDR_SUPPORTED_VERSIONS = (QUALYS_VMDR_API_VERSION_2_0, QUALYS_VMDR_API_VERSION_4_0)
QUALYS_VMDR_DEFAULT_VERSION = QUALYS_VMDR_API_VERSION_4_0


@dataclass
class QualysVmdrEndpointConfig:
    name: str
    path: str  # version-independent request path, e.g. "/api/2.0/fo/asset/host/"
    item_tag: str  # element tag of one record in the XML response (e.g. "HOST")
    # Static query params sent on every request (the FO API routes on `action=list`).
    params: dict[str, str] = field(default_factory=dict)
    # Server-side "since" filter param for incremental syncs (None = full refresh only).
    incremental_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Field to partition by — must be a STABLE field (first_found/launch style, never last_*).
    partition_key: Optional[str] = None
    # Records per truncated batch; None for endpoints that don't accept truncation_limit.
    truncation_limit: Optional[int] = None
    # Flatten each HOST's DETECTION_LIST into one row per detection (Host List Detection only).
    flatten_host_detections: bool = False
    should_sync_default: bool = True
    # Per-version path overrides for endpoints whose route moved between vendor versions. Absent
    # keys fall through to `path` — that is the correct version-independent route, not silent drift,
    # since only the KnowledgeBase endpoint diverges.
    path_overrides: dict[str, str] = field(default_factory=dict)
    # Source-level versions on which this endpoint authenticates with a JWT Bearer token minted at
    # the Qualys gateway, rather than HTTP basic auth. Empty = basic auth on every version.
    jwt_versions: frozenset[str] = frozenset()

    def resolve_path(self, api_version: str) -> str:
        return self.path_overrides.get(api_version, self.path)

    def requires_jwt(self, api_version: str) -> bool:
        return api_version in self.jwt_versions


QUALYS_VMDR_ENDPOINTS: dict[str, QualysVmdrEndpointConfig] = {
    # Asset inventory: one row per host in the subscription. `vm_scan_since` is a server-side
    # filter on the host's last VM scan datetime, so incremental syncs only pick up hosts that
    # have been (re)scanned since the watermark.
    "hosts": QualysVmdrEndpointConfig(
        name="hosts",
        path="/api/2.0/fo/asset/host/",
        item_tag="HOST",
        params={"action": "list", "details": "All"},
        incremental_param="vm_scan_since",
        incremental_fields=[
            {
                "label": "last_vuln_scan_datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "last_vuln_scan_datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["id"],
        truncation_limit=1000,
    ),
    # The core VMDR feed: one row per (host, detection). `detection_updated_since` is a
    # server-side filter on the detection's last update, so incremental syncs re-pull rows whose
    # status/severity changed. Lower truncation limit than the other endpoints because each host
    # record carries its full detection list (including RESULTS text).
    "host_list_detection": QualysVmdrEndpointConfig(
        name="host_list_detection",
        path="/api/2.0/fo/asset/host/vm/detection/",
        item_tag="HOST",
        params={"action": "list"},
        incremental_param="detection_updated_since",
        incremental_fields=[
            {
                "label": "last_update_datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "last_update_datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["unique_vuln_id"],
        partition_key="first_found_datetime",
        truncation_limit=500,
        flatten_host_detections=True,
    ),
    # VM scan history. The scan list endpoint has no truncation pagination — it returns every
    # scan matching the filters in one response — so incremental filtering on launch datetime
    # is what keeps ongoing syncs cheap.
    "scans": QualysVmdrEndpointConfig(
        name="scans",
        path="/api/2.0/fo/scan/",
        item_tag="SCAN",
        params={"action": "list"},
        incremental_param="launched_after_datetime",
        incremental_fields=[
            {
                "label": "launch_datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "launch_datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["ref"],
        partition_key="launch_datetime",
        truncation_limit=None,
    ),
    # Vulnerability definitions (QIDs). Requires the "KnowledgeBase download" option enabled on
    # the Qualys subscription, so it's off by default. `details=Basic` keeps rows compact
    # (skips the large DIAGNOSIS/CONSEQUENCE/SOLUTION HTML blobs).
    "knowledge_base": QualysVmdrEndpointConfig(
        name="knowledge_base",
        path="/api/2.0/fo/knowledge_base/vuln/",
        item_tag="VULN",
        params={"action": "list", "details": "Basic"},
        incremental_param="last_modified_after",
        incremental_fields=[
            {
                "label": "last_service_modification_datetime",
                "type": IncrementalFieldType.DateTime,
                "field": "last_service_modification_datetime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        primary_keys=["qid"],
        truncation_limit=None,
        should_sync_default=False,
        # Qualys is sunsetting KnowledgeBase 2.0; 4.0 serves the same feed but only over JWT Bearer.
        path_overrides={QUALYS_VMDR_API_VERSION_4_0: "/api/4.0/fo/knowledge_base/vuln/"},
        jwt_versions=frozenset({QUALYS_VMDR_API_VERSION_4_0}),
    ),
}

ENDPOINTS = tuple(QUALYS_VMDR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in QUALYS_VMDR_ENDPOINTS.items()
}
