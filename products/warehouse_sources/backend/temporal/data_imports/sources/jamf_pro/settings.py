from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# The computers-inventory endpoint returns only the GENERAL section unless asked for more.
# This curated set covers the fields device-inventory reporting actually uses while leaving
# out the unbounded per-device lists (APPLICATIONS, CERTIFICATES, FONTS, ...) that would blow
# up row size on large fleets.
COMPUTERS_INVENTORY_SECTIONS = [
    "GENERAL",
    "HARDWARE",
    "OPERATING_SYSTEM",
    "USER_AND_LOCATION",
    "SECURITY",
    "DISK_ENCRYPTION",
    "PURCHASING",
    "STORAGE",
    "GROUP_MEMBERSHIPS",
]


@dataclass(frozen=False)
class JamfProEndpointConfig:
    name: str
    path: str
    # Jamf Pro API collection endpoints return {"totalCount": N, "results": [...]} and take
    # page / page-size / sort. A few (sites, computer-groups) return a plain JSON array.
    paginated: bool = True
    page_size: int = 200
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Explicit sort keeps page boundaries stable while paginating a full refresh.
    sort: Optional[str] = "id:asc"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # RSQL field used to build the server-side incremental filter (e.g. general.reportDate).
    # Only set when the endpoint documents RSQL filtering on a timestamp.
    rsql_incremental_field: Optional[str] = None
    # Column name the incremental cursor is exposed under in the yielded rows. The pipeline
    # reads the watermark from a top-level column, so nested API fields get hoisted to this.
    # Leave unset when the RSQL field is already a top-level column.
    default_incremental_field: Optional[str] = None
    # RSQL filter sent whenever no incremental filter applies, for endpoints that reject a
    # request without any filter.
    default_filter: Optional[str] = None
    # Sort applied on incremental runs so rows arrive in ascending cursor order and the
    # watermark can checkpoint per batch.
    incremental_sort: Optional[str] = None
    # Repeated `section=` values (computers-inventory only).
    sections: list[str] = field(default_factory=list)
    # Whether responses may enter opt-in HTTP sample capture. Disabled for endpoints whose
    # bodies carry arbitrary customer content the name-based scrubbers can't recognise.
    capture_samples: bool = True
    # Fan-out children: `path` holds an `{id}` placeholder filled from each row of this parent
    # endpoint, and the parent id is written to `parent_id_field` on every child row.
    parent: Optional[str] = None
    parent_id_field: Optional[str] = None


JAMF_PRO_ENDPOINTS: dict[str, JamfProEndpointConfig] = {
    # Computer inventory is the only Jamf Pro collection that documents RSQL filtering on a
    # timestamp (general.reportDate advances on every inventory submission), so it is the only
    # incremental-capable table. The nested cursor is hoisted to a top-level `report_date`
    # column in the transport.
    "computers": JamfProEndpointConfig(
        name="computers",
        path="/api/v1/computers-inventory",
        page_size=100,
        rsql_incremental_field="general.reportDate",
        default_incremental_field="report_date",
        incremental_sort="general.reportDate:asc",
        incremental_fields=[_datetime_incremental_field("report_date")],
        sections=COMPUTERS_INVENTORY_SECTIONS,
    ),
    # The v2 mobile devices list carries identity fields only (no timestamps), so it is
    # full-refresh only. The richer /detail inventory endpoint is a follow-up.
    "mobile_devices": JamfProEndpointConfig(
        name="mobile_devices",
        path="/api/v2/mobile-devices",
    ),
    "buildings": JamfProEndpointConfig(
        name="buildings",
        path="/api/v1/buildings",
    ),
    "departments": JamfProEndpointConfig(
        name="departments",
        path="/api/v1/departments",
    ),
    "categories": JamfProEndpointConfig(
        name="categories",
        path="/api/v1/categories",
    ),
    "sites": JamfProEndpointConfig(
        name="sites",
        path="/api/v1/sites",
        paginated=False,
        sort=None,
    ),
    "computer_groups": JamfProEndpointConfig(
        name="computer_groups",
        path="/api/v1/computer-groups",
        paginated=False,
        sort=None,
    ),
    "scripts": JamfProEndpointConfig(
        name="scripts",
        path="/api/v1/scripts",
        # scriptContents routinely embeds deployment credentials; keep it out of sample capture.
        capture_samples=False,
    ),
    "packages": JamfProEndpointConfig(
        name="packages",
        path="/api/v1/packages",
    ),
    "users": JamfProEndpointConfig(
        name="users",
        path="/api/v1/users",
    ),
    # The endpoint rejects requests without a filter, so full refreshes send an always-true
    # dateSent bound. Commands keep their dateSent as their state moves from pending to
    # acknowledged, so an incremental run only picks up commands sent since the last sync. A
    # full refresh refreshes the state of older commands.
    "mdm_commands": JamfProEndpointConfig(
        name="mdm_commands",
        path="/api/v2/mdm/commands",
        primary_keys=["uuid"],
        sort="dateSent:asc",
        rsql_incremental_field="dateSent",
        incremental_sort="dateSent:asc",
        incremental_fields=[_datetime_incremental_field("dateSent")],
        default_filter='dateSent>="1970-01-01T00:00:00.000Z"',
    ),
    # Unpaginated: the endpoint takes only `filter` and returns every status in one response.
    # `updated` advances whenever a device's update status changes.
    "managed_software_update_statuses": JamfProEndpointConfig(
        name="managed_software_update_statuses",
        path="/api/v1/managed-software-updates/update-statuses",
        paginated=False,
        sort=None,
        primary_keys=["osUpdatesStatusId"],
        rsql_incremental_field="updated",
        incremental_fields=[_datetime_incremental_field("updated")],
    ),
    "patch_software_title_configurations": JamfProEndpointConfig(
        name="patch_software_title_configurations",
        path="/api/v3/patch-software-title-configurations",
        paginated=False,
        sort=None,
    ),
    "patch_reports": JamfProEndpointConfig(
        name="patch_reports",
        path="/api/v3/patch-software-title-configurations/{id}/patch-report",
        primary_keys=["softwareTitleConfigurationId", "deviceId"],
        sort="deviceId:asc",
        parent="patch_software_title_configurations",
        parent_id_field="softwareTitleConfigurationId",
    ),
    "patch_summaries": JamfProEndpointConfig(
        name="patch_summaries",
        path="/api/v3/patch-software-title-configurations/{id}/patch-summary",
        paginated=False,
        sort=None,
        primary_keys=["softwareTitleConfigurationId"],
        parent="patch_software_title_configurations",
        parent_id_field="softwareTitleConfigurationId",
    ),
}

ENDPOINTS = tuple(JAMF_PRO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in JAMF_PRO_ENDPOINTS.items()
}
