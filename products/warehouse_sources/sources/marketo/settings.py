from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Marketo splits its surface across three transports that share one host and one token:
#
# - ``rest_token``: /rest/v1 list endpoints paginated with an opaque ``nextPageToken`` and a
#   ``moreResult`` flag.
# - ``asset_offset``: /rest/asset/v1 endpoints paginated with ``offset`` + ``maxReturn`` (200 max).
# - ``bulk``: the async Bulk Extract API (create -> enqueue -> poll -> download CSV). Leads and
#   activities have no usable synchronous list endpoint, so they can only come this way.
#
# Two fan-out shapes walk a parent endpoint and page a /rest/v1 child per parent row:
#
# - ``list_members``: ``nextPageToken`` paging per static list.
# - ``program_members``: ``nextPageToken`` paging per program and per ``updatedAt`` window, because
#   the endpoint needs a filter and only ``updatedAt`` reaches every member.
MarketoTransport = Literal["rest_token", "asset_offset", "bulk", "list_members", "program_members"]

# Marketo caps a bulk export's date filter at 31 days; stay under it.
BULK_WINDOW_DAYS = 30
# Asset API hard cap.
ASSET_MAX_RETURN = 200
# /rest/v1 list endpoints cap batchSize at 300.
REST_BATCH_SIZE = 300
# Marketo rejects a program member updatedAt range longer than seven days.
PROGRAM_MEMBER_WINDOW_DAYS = 7
# Folder browse defaults to two levels; nested program trees go deeper than that.
FOLDER_MAX_DEPTH = 20


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=True)
class MarketoEndpointConfig:
    name: str
    transport: MarketoTransport
    # For rest_token/asset_offset this is the request path. For bulk it is the export object
    # segment ("leads" / "activities") used to build /bulk/v1/<object>/export/... . Fan-out paths
    # carry a ``{parent_id}`` placeholder.
    path: str
    primary_key: list[str]
    # Set only where a real server-side timestamp filter exists (bulk exports filter on a
    # mandatory createdAt range, program members on updatedAt). Asset and other /rest/v1 list
    # endpoints stay full refresh: their updated-since filters are undocumented for some resources
    # and the collections are small.
    incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    # CSV columns to coerce back to integers — bulk downloads arrive as all-string CSV.
    int_columns: tuple[str, ...] = ()
    # Bulk lead exports must name every column they want; activities have a fixed column set.
    needs_field_list: bool = False
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fan-out only: the endpoint whose rows are the parents, and the column that carries the
    # parent id on each child row.
    parent: Optional[str] = None
    parent_key: Optional[str] = None

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_field is None:
            return []
        return [_datetime_field(self.incremental_field)]


MARKETO_ENDPOINTS: dict[str, MarketoEndpointConfig] = {
    "leads": MarketoEndpointConfig(
        name="leads",
        transport="bulk",
        path="leads",
        primary_key=["id"],
        incremental_field="createdAt",
        partition_key="createdAt",
        int_columns=("id",),
        needs_field_list=True,
    ),
    "activities": MarketoEndpointConfig(
        name="activities",
        transport="bulk",
        path="activities",
        # marketoGUID is the only globally unique identifier on an activity row.
        primary_key=["marketoGUID"],
        incremental_field="activityDate",
        partition_key="activityDate",
        int_columns=("leadId", "activityTypeId", "campaignId", "primaryAttributeValueId"),
    ),
    "activity_types": MarketoEndpointConfig(
        name="activity_types",
        transport="rest_token",
        path="/rest/v1/activities/types.json",
        primary_key=["id"],
    ),
    "campaigns": MarketoEndpointConfig(
        name="campaigns",
        transport="rest_token",
        path="/rest/v1/campaigns.json",
        primary_key=["id"],
        partition_key="createdAt",
    ),
    "lists": MarketoEndpointConfig(
        name="lists",
        transport="rest_token",
        path="/rest/v1/lists.json",
        primary_key=["id"],
        partition_key="createdAt",
    ),
    # Asset API timestamps come back as "2016-02-25T18:36:58Z+0000", which is not a format the
    # datetime partitioner can parse — these stay unpartitioned. They are small collections.
    "programs": MarketoEndpointConfig(
        name="programs",
        transport="asset_offset",
        path="/rest/asset/v1/programs.json",
        primary_key=["id"],
    ),
    "emails": MarketoEndpointConfig(
        name="emails",
        transport="asset_offset",
        path="/rest/asset/v1/emails.json",
        primary_key=["id"],
    ),
    "forms": MarketoEndpointConfig(
        name="forms",
        transport="asset_offset",
        path="/rest/asset/v1/forms.json",
        primary_key=["id"],
    ),
    "landing_pages": MarketoEndpointConfig(
        name="landing_pages",
        transport="asset_offset",
        path="/rest/asset/v1/landingPages.json",
        primary_key=["id"],
    ),
    "smart_campaigns": MarketoEndpointConfig(
        name="smart_campaigns",
        transport="asset_offset",
        path="/rest/asset/v1/smartCampaigns.json",
        primary_key=["id"],
    ),
    # Folders and programs number their ids separately, and folderType tells the two apart.
    "folders": MarketoEndpointConfig(
        name="folders",
        transport="asset_offset",
        path="/rest/asset/v1/folders.json",
        primary_key=["id", "folderType"],
        extra_params={"maxDepth": str(FOLDER_MAX_DEPTH)},
    ),
    "channels": MarketoEndpointConfig(
        name="channels",
        transport="asset_offset",
        path="/rest/asset/v1/channels.json",
        primary_key=["id"],
    ),
    "program_members": MarketoEndpointConfig(
        name="program_members",
        transport="program_members",
        path="/rest/v1/programs/{parent_id}/members.json",
        primary_key=["programId", "leadId"],
        incremental_field="updatedAt",
        partition_key="membershipDate",
        parent="programs",
        parent_key="programId",
    ),
    "list_members": MarketoEndpointConfig(
        name="list_members",
        transport="list_members",
        path="/rest/v1/lists/{parent_id}/leads.json",
        # Each row is a lead record, so `id` is the lead id.
        primary_key=["listId", "id"],
        partition_key="createdAt",
        parent="lists",
        parent_key="listId",
    ),
}

ENDPOINTS = tuple(MARKETO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MARKETO_ENDPOINTS.items()
}
