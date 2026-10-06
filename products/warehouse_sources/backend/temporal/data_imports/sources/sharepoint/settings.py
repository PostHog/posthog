from dataclasses import dataclass
from enum import StrEnum
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
# Entra ID (Azure AD) token endpoint; the tenant id is interpolated into the path.
LOGIN_BASE_URL = "https://login.microsoftonline.com"
# Client-credentials scope for Microsoft Graph. The app's granted application permissions
# (Sites.Read.All or Sites.Selected) decide what the token can actually read.
TOKEN_SCOPE = "https://graph.microsoft.com/.default"

# Hard cap per collection walk so a `@odata.nextLink` that never ends can't spin forever. Far
# above any realistic list or document library at Graph's default page sizes.
MAX_PAGES_PER_COLLECTION = 50_000

SITE_ID_COLUMN = "site_id"
LIST_ID_COLUMN = "list_id"
DRIVE_ID_COLUMN = "drive_id"


class SharePointEndpoint(StrEnum):
    SITES = "sites"
    LISTS = "lists"
    LIST_ITEMS = "list_items"
    DRIVES = "drives"
    DRIVE_ITEMS = "drive_items"


@dataclass(frozen=True)
class SharePointEndpointConfig:
    name: SharePointEndpoint
    primary_keys: list[str]
    description: str
    # Stable datetime column for datetime partitioning (None = no datetime partitioning).
    partition_key: Optional[str] = None


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
}

ENDPOINTS = tuple(SHAREPOINT_ENDPOINTS.keys())

# Graph has no reliable server-side "modified since" filter across lists and drives (list
# filters only work on indexed columns), so every table is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
