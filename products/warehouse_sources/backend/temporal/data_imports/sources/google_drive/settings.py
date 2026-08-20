from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Partial-response field selections. Drive rejects an unknown field name with a 400, so every
# name here must exist on the corresponding v3 resource — add fields from the reference docs only.
FILE_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "mimeType",
    "description",
    "starred",
    "trashed",
    "explicitlyTrashed",
    "trashedTime",
    "parents",
    "spaces",
    "version",
    "webViewLink",
    "webContentLink",
    "iconLink",
    "hasThumbnail",
    "thumbnailLink",
    "thumbnailVersion",
    "viewedByMe",
    "viewedByMeTime",
    "createdTime",
    "modifiedTime",
    "modifiedByMe",
    "modifiedByMeTime",
    "sharedWithMeTime",
    "sharingUser",
    "owners",
    "lastModifyingUser",
    "shared",
    "ownedByMe",
    "driveId",
    "permissionIds",
    "folderColorRgb",
    "originalFilename",
    "fullFileExtension",
    "fileExtension",
    "md5Checksum",
    "size",
    "quotaBytesUsed",
    "headRevisionId",
    "isAppAuthorized",
    "copyRequiresWriterPermission",
    "writersCanShare",
    "shortcutDetails",
)

DRIVE_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "colorRgb",
    "backgroundImageLink",
    "themeId",
    "createdTime",
    "hidden",
    "restrictions",
)

PERMISSION_FIELDS: tuple[str, ...] = (
    "id",
    "type",
    "kind",
    "emailAddress",
    "domain",
    "role",
    "displayName",
    "photoLink",
    "deleted",
    "expirationTime",
    "permissionDetails",
    "pendingOwner",
)


@dataclass(frozen=True)
class GoogleDriveEndpointConfig:
    name: str
    # Path under the versioned Drive API base. Fan-out paths carry a {drive_id} placeholder.
    path: str
    # Response key holding the page's records.
    data_path: str
    # Resource fields requested through the `fields` partial-response param.
    resource_fields: tuple[str, ...]
    primary_keys: list[str]
    # Drive caps files.list at 1000 and drives.list / permissions.list at 100.
    page_size: int
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Cursor fields the Drive search query (`q=<field> > '<RFC3339>'`) genuinely filters
    # server-side. Empty keeps the endpoint full-refresh only.
    search_filter_fields: tuple[str, ...] = ()
    # Whether the endpoint accepts `orderBy` at all — only files.list does.
    supports_order_by: bool = False
    # `orderBy` value for a full walk: an immutable field, so rows edited mid-walk can't
    # reshuffle pages under the paginator.
    stable_order_by: Optional[str] = None
    # Immutable datetime field used for partitioning (never a modified/updated field).
    partition_key: Optional[str] = None
    # Fetched once per shared drive, with {drive_id} substituted into the path and the
    # parent drive's identity injected into every row.
    fan_out_over_drives: bool = False
    # Whether the endpoint takes the shared-drive scoping params (`corpora` / `driveId` /
    # `includeItemsFromAllDrives`) derived from the source's optional drive id.
    applies_drive_scope: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)

    @property
    def supports_incremental(self) -> bool:
        return bool(self.search_filter_fields)

    @property
    def response_fields(self) -> str:
        return f"nextPageToken,{self.data_path}({','.join(self.resource_fields)})"


GOOGLE_DRIVE_ENDPOINTS: dict[str, GoogleDriveEndpointConfig] = {
    "files": GoogleDriveEndpointConfig(
        name="files",
        path="/files",
        data_path="files",
        resource_fields=FILE_FIELDS,
        primary_keys=["id"],
        page_size=1000,
        # Both timestamps are filterable operators in Drive's search syntax, so either works as a
        # server-side cursor; modifiedTime is the default because it catches edits, not just uploads.
        incremental_fields=[incremental_field("modifiedTime"), incremental_field("createdTime")],
        default_incremental_field="modifiedTime",
        search_filter_fields=("modifiedTime", "createdTime"),
        supports_order_by=True,
        stable_order_by="createdTime",
        partition_key="createdTime",
        applies_drive_scope=True,
    ),
    "drives": GoogleDriveEndpointConfig(
        name="drives",
        path="/drives",
        data_path="drives",
        resource_fields=DRIVE_FIELDS,
        primary_keys=["id"],
        page_size=100,
        # drives.list takes a `q`, but a shared drive's only filterable timestamp is the immutable
        # createdTime — renames and setting changes wouldn't resync. Volume is tiny (drives per
        # org, not files), so full refresh keeps the table correct for a negligible cost.
    ),
    "drive_permissions": GoogleDriveEndpointConfig(
        name="drive_permissions",
        path="/files/{drive_id}/permissions",
        data_path="permissions",
        resource_fields=PERMISSION_FIELDS,
        # Permission ids are unique per file, and a shared drive's id doubles as its root folder's
        # file id, so the parent drive id is required for a table-wide unique key.
        primary_keys=["drive_id", "id"],
        page_size=100,
        fan_out_over_drives=True,
        # Permission objects carry no timestamps to filter on; full refresh only.
        extra_params={"supportsAllDrives": "true"},
    ),
}

ENDPOINTS = tuple(GOOGLE_DRIVE_ENDPOINTS.keys())

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "drive_permissions": "Access grants on each shared drive. My Drive files are not covered.",
}
