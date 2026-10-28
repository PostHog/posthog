from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
# Entra ID (Azure AD) token endpoint; the tenant id is interpolated into the path.
LOGIN_BASE_URL = "https://login.microsoftonline.com"
# Client-credentials scope for Microsoft Graph. The app's granted application permissions
# (Sites.Read.All or Sites.Selected) decide what the token can actually read.
TOKEN_SCOPE = "https://graph.microsoft.com/.default"

# Hard cap per collection walk so a `@odata.nextLink` that never ends can't spin forever. Far
# above any realistic list or document library at Graph's default page sizes.
MAX_PAGES_PER_COLLECTION = 50_000
MAX_FILES = 1000
FILE_EXTENSIONS = {".csv", ".tsv"}
EXCEL_EXTENSIONS = {".xlsx"}
# Discovery downloads each workbook to list its worksheets.
MAX_EXCEL_FILES = 100
FILE_NOT_FOUND_ERROR = "The SharePoint file for table"
PATTERN_ERROR = "The file pattern isn't a valid regular expression"

SITE_ID_COLUMN = "site_id"
LIST_ID_COLUMN = "list_id"
DRIVE_ID_COLUMN = "drive_id"
ITEM_ID_COLUMN = "item_id"

# Graph rejects a daily activity range of 90 days or more.
ACTIVITY_STATS_WINDOW = timedelta(days=89)
# Graph aggregates activity late, so each incremental sync reads the last days again.
ACTIVITY_STATS_INCREMENTAL_LOOKBACK_SECONDS = 2 * 24 * 60 * 60


class SharePointEndpoint(StrEnum):
    SITES = "sites"
    LISTS = "lists"
    LIST_ITEMS = "list_items"
    DRIVES = "drives"
    DRIVE_ITEMS = "drive_items"
    CONTENT_TYPES = "content_types"
    SITE_ACTIVITY_STATS = "site_activity_stats"
    DRIVE_ITEM_VERSIONS = "drive_item_versions"
    LIST_ITEM_VERSIONS = "list_item_versions"


@dataclass(frozen=True)
class SharePointEndpointConfig:
    name: SharePointEndpoint
    primary_keys: list[str]
    description: str
    # Stable datetime column for datetime partitioning (None = no datetime partitioning).
    partition_key: Optional[str] = None
    should_sync_default: bool = True


SHAREPOINT_ENDPOINTS: dict[str, SharePointEndpointConfig] = {
    SharePointEndpoint.SITES: SharePointEndpointConfig(
        name=SharePointEndpoint.SITES,
        primary_keys=["id"],
        # `getAllSites` omits `createdDateTime`, so sites can't be partitioned on it.
        description="SharePoint sites the app can read, excluding personal OneDrive sites",
    ),
    SharePointEndpoint.LISTS: SharePointEndpointConfig(
        name=SharePointEndpoint.LISTS,
        primary_keys=[SITE_ID_COLUMN, "id"],
        description="Lists and document libraries in each site",
        partition_key="createdDateTime",
    ),
    SharePointEndpoint.LIST_ITEMS: SharePointEndpointConfig(
        name=SharePointEndpoint.LIST_ITEMS,
        # Item ids are only unique within their list.
        primary_keys=[SITE_ID_COLUMN, LIST_ID_COLUMN, "id"],
        description="Items in every visible list, with the list's column values in `fields`",
        partition_key="createdDateTime",
    ),
    SharePointEndpoint.DRIVES: SharePointEndpointConfig(
        name=SharePointEndpoint.DRIVES,
        primary_keys=[SITE_ID_COLUMN, "id"],
        description="Document libraries (drives) in each site",
        partition_key="createdDateTime",
    ),
    SharePointEndpoint.DRIVE_ITEMS: SharePointEndpointConfig(
        name=SharePointEndpoint.DRIVE_ITEMS,
        # Drive item ids are only guaranteed unique within their drive.
        primary_keys=[DRIVE_ID_COLUMN, "id"],
        description="File and folder metadata in every document library",
        partition_key="createdDateTime",
    ),
    SharePointEndpoint.CONTENT_TYPES: SharePointEndpointConfig(
        name=SharePointEndpoint.CONTENT_TYPES,
        # Built-in content type ids such as `0x0101` repeat in every site.
        primary_keys=[SITE_ID_COLUMN, "id"],
        description="Content types defined in each site, to resolve the content type of list items",
    ),
    SharePointEndpoint.SITE_ACTIVITY_STATS: SharePointEndpointConfig(
        name=SharePointEndpoint.SITE_ACTIVITY_STATS,
        primary_keys=[SITE_ID_COLUMN, "startDateTime"],
        description=(
            "Daily access, create, edit, delete, and move counts for each site. Graph keeps the last 89 days, "
            "so sync incrementally to keep older days"
        ),
        partition_key="startDateTime",
    ),
    SharePointEndpoint.DRIVE_ITEM_VERSIONS: SharePointEndpointConfig(
        name=SharePointEndpoint.DRIVE_ITEM_VERSIONS,
        # Version ids such as `1.0` repeat for every file.
        primary_keys=[DRIVE_ID_COLUMN, ITEM_ID_COLUMN, "id"],
        # No partition key: the current version keeps its id while it is edited, so its modified
        # time changes.
        description=("Version history of every file in every document library. Each sync makes one request per file"),
        # One request per file or list item is too costly to turn on without the user choosing it.
        should_sync_default=False,
    ),
    SharePointEndpoint.LIST_ITEM_VERSIONS: SharePointEndpointConfig(
        name=SharePointEndpoint.LIST_ITEM_VERSIONS,
        primary_keys=[SITE_ID_COLUMN, LIST_ID_COLUMN, ITEM_ID_COLUMN, "id"],
        description=(
            "Version history of every item in every visible list, with the column values of each version in "
            "`fields`. Each sync makes one request per item"
        ),
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(SHAREPOINT_ENDPOINTS.keys())

# Graph has no reliable server-side "modified since" filter across lists and drives (list
# filters only work on indexed columns), so those tables are full refresh. Activity stats take
# the start of their date range in the request.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    **{name: [] for name in ENDPOINTS},
    SharePointEndpoint.SITE_ACTIVITY_STATS: [
        IncrementalField(
            label="startDateTime",
            type=IncrementalFieldType.DateTime,
            field="startDateTime",
            field_type=IncrementalFieldType.DateTime,
        )
    ],
}
