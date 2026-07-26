from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Microsoft Graph caps `$top` at 999 for directory objects and 1000 for the auditLogs resources.
DIRECTORY_PAGE_SIZE = 999
AUDIT_LOG_PAGE_SIZE = 1000

# `/users` returns only a small default property set, so the columns a warehouse actually wants
# (createdDateTime, accountEnabled, department, userType, ...) have to be requested explicitly.
USER_SELECT = (
    "id,displayName,userPrincipalName,mail,mailNickname,givenName,surname,jobTitle,department,"
    "companyName,officeLocation,city,state,country,postalCode,streetAddress,usageLocation,"
    "accountEnabled,createdDateTime,userType,employeeId,mobilePhone,businessPhones,"
    "preferredLanguage,proxyAddresses,onPremisesSyncEnabled,onPremisesSamAccountName"
)

# Requested explicitly for the same reason: `createdDateTime` and the dynamic-membership rule
# columns are not part of the `/groups` default projection.
GROUP_SELECT = (
    "id,displayName,description,createdDateTime,renewedDateTime,mail,mailEnabled,mailNickname,"
    "securityEnabled,groupTypes,visibility,classification,membershipRule,"
    "membershipRuleProcessingState,onPremisesSyncEnabled"
)


@dataclass(frozen=True)
class EntraEndpointConfig:
    name: str
    path: str
    # Application permission (admin-consented) the endpoint needs. Surfaced verbatim to the user
    # when a probe comes back 403 so they know exactly what to grant.
    required_permission: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `$select` projection. Only set where the default projection omits columns we need — an
    # unnecessary `$select` would silently drop columns a user expects.
    select: Optional[str] = None
    # `$top`. None for the singleton/small collections that document no paging support, so we
    # never send a query parameter the endpoint doesn't accept.
    page_size: Optional[int] = None
    # Stable creation-time column for datetime partitioning. Only set where the projection above
    # guarantees the column is present.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # OData property used to build the `<field> ge <timestamp>` server-side `$filter`. Only the
    # auditLogs resources document one; every other endpoint is full refresh.
    incremental_filter_field: Optional[str] = None
    # The auditLogs resources return newest-first and reject no-op parameters, so we don't send
    # `$orderby`; declare desc so the pipeline checkpoints the watermark at the end of the run.
    sort_mode: SortMode = "asc"
    # Fan-out parent endpoint name. The path then carries a `{parent_id}` placeholder.
    parent: Optional[str] = None
    # Column the parent's id is written to on each child row (composite primary key member).
    parent_id_column: Optional[str] = None
    # Endpoint used for the create-time / per-table permission probe. Defaults to `path`; fan-out
    # children override it because their real path needs a parent id we don't have yet.
    probe_path: Optional[str] = None
    should_sync_default: bool = True

    @property
    def permission_probe_path(self) -> str:
        return self.probe_path or self.path

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


ENTRA_ENDPOINTS: dict[str, EntraEndpointConfig] = {
    "Users": EntraEndpointConfig(
        name="Users",
        path="/users",
        required_permission="User.Read.All",
        select=USER_SELECT,
        page_size=DIRECTORY_PAGE_SIZE,
        partition_key="createdDateTime",
    ),
    "Groups": EntraEndpointConfig(
        name="Groups",
        path="/groups",
        required_permission="Group.Read.All",
        select=GROUP_SELECT,
        page_size=DIRECTORY_PAGE_SIZE,
        partition_key="createdDateTime",
    ),
    # Fan-out: one row per (group, member). Members are a heterogeneous directoryObject
    # collection (users, groups, devices, service principals), so no `$select` — the member type
    # is carried by `@odata.type`, normalized into `member_type` by the row mapper.
    "GroupMembers": EntraEndpointConfig(
        name="GroupMembers",
        path="/groups/{parent_id}/members",
        required_permission="GroupMember.Read.All",
        primary_keys=["group_id", "id"],
        page_size=DIRECTORY_PAGE_SIZE,
        parent="Groups",
        parent_id_column="group_id",
        probe_path="/groups",
    ),
    "Applications": EntraEndpointConfig(
        name="Applications",
        path="/applications",
        required_permission="Application.Read.All",
        page_size=DIRECTORY_PAGE_SIZE,
    ),
    "ServicePrincipals": EntraEndpointConfig(
        name="ServicePrincipals",
        path="/servicePrincipals",
        required_permission="Application.Read.All",
        page_size=DIRECTORY_PAGE_SIZE,
    ),
    "Devices": EntraEndpointConfig(
        name="Devices",
        path="/devices",
        required_permission="Device.Read.All",
        page_size=DIRECTORY_PAGE_SIZE,
    ),
    "DirectoryRoles": EntraEndpointConfig(
        name="DirectoryRoles",
        path="/directoryRoles",
        required_permission="RoleManagement.Read.Directory",
    ),
    "SubscribedSkus": EntraEndpointConfig(
        name="SubscribedSkus",
        path="/subscribedSkus",
        required_permission="Organization.Read.All",
    ),
    "Organization": EntraEndpointConfig(
        name="Organization",
        path="/organization",
        required_permission="Organization.Read.All",
    ),
    "DirectoryAudits": EntraEndpointConfig(
        name="DirectoryAudits",
        path="/auditLogs/directoryAudits",
        required_permission="AuditLog.Read.All",
        page_size=AUDIT_LOG_PAGE_SIZE,
        partition_key="activityDateTime",
        incremental_fields=[incremental_field("activityDateTime")],
        incremental_filter_field="activityDateTime",
        sort_mode="desc",
    ),
    # Sign-in logs additionally need a Microsoft Entra ID P1/P2 tenant licence, so they start
    # disabled rather than failing a one-shot setup on a free-tier tenant.
    "SignIns": EntraEndpointConfig(
        name="SignIns",
        path="/auditLogs/signIns",
        required_permission="AuditLog.Read.All",
        page_size=AUDIT_LOG_PAGE_SIZE,
        partition_key="createdDateTime",
        incremental_fields=[incremental_field("createdDateTime")],
        incremental_filter_field="createdDateTime",
        sort_mode="desc",
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(ENTRA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENTRA_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in ENTRA_ENDPOINTS.items()}
