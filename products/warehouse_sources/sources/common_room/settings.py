from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

BASE_URL = "https://api.commonroom.io/api/v2"
API_HOST = "api.commonroom.io"

# Activities can reach Common Room some time after they happened (a provider sync catches up), so an
# incremental sync reads the last days again. The merge on `id` drops the duplicates.
ACTIVITIES_LOOKBACK_DAYS = 3

# Common Room returns only `id` and `name` for a contact or an organization unless `cols` asks for more.
# These are the documented columns, without the large summary and history columns.
CONTACT_COLUMNS = (
    "avatarUrl",
    "fullName",
    "location",
    "primaryEmail",
    "phoneNumbers",
    "title",
    "companyName",
    "companyWebsite",
    "linkedInUrls",
    "gitHubUrls",
    "xUrls",
    "profiles",
    "jobChangeDate",
    "currentCompany",
    "previousCompany",
    "leadScores",
    "segments",
    "tags",
    "url",
    "activityCount7d",
    "activityCount28d",
    "activityCountAll",
    "cf_*",
)
ORGANIZATION_COLUMNS = (
    "about",
    "contactsCount",
    "employees",
    "linkedInUrl",
    "profiles",
    "revenueRangeMax",
    "revenueRangeMin",
    "subIndustry",
    "technologies",
    "location",
    "leadScores",
    "segments",
    "tags",
    "url",
    "cf_*",
)
ACTIVITY_COLUMNS = (
    "contactId",
    "content",
    "isUserInitiated",
    "participantCount",
    "providerId",
    "providerName",
    "replyCount",
    "sentiment",
    "subSourceNames",
    "url",
)
SEGMENT_COLUMNS = ("entityCount", "url", "summary", "automationStatus")
WEBSITE_VISIT_COLUMNS = ("url", "contactId", "organizationId")
OBJECT_COLUMNS = ("recordKey", "segments", "tags", "url", "cf_*")
JOB_OPENING_COLUMNS = ("jobDescription",)

ACTIVITY_TIME_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "activityTime",
        "type": IncrementalFieldType.DateTime,
        "field": "activityTime",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class CommonRoomEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # False for the endpoints that return every row in one response and take no `limit` or `cursor`.
    paginated: bool = True
    page_size: int = 1000
    columns: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Set once when the row is created, so it is a stable partition key.
    partition_key: Optional[str] = None
    # The parent endpoint whose `id` each request of this endpoint needs, in `resolve_param`.
    parent: Optional[str] = None
    resolve_param: Optional[str] = None
    # A resume starts the parent listing at its saved page. The parent must list in a stable order.
    resume_parent_pagination: bool = False


COMMON_ROOM_ENDPOINTS: dict[str, CommonRoomEndpointConfig] = {
    "contacts": CommonRoomEndpointConfig(
        name="contacts",
        path="/contacts",
        primary_keys=["id"],
        # Many columns per contact, so a smaller page keeps each response fast.
        page_size=500,
        columns=CONTACT_COLUMNS,
        params={"sort": "id", "direction": "asc"},
    ),
    "organizations": CommonRoomEndpointConfig(
        name="organizations",
        path="/organizations",
        primary_keys=["id"],
        page_size=500,
        columns=ORGANIZATION_COLUMNS,
        params={"sort": "id", "direction": "asc"},
    ),
    "activities": CommonRoomEndpointConfig(
        name="activities",
        path="/activities",
        primary_keys=["id"],
        columns=ACTIVITY_COLUMNS,
        params={"sort": "activityTime", "direction": "asc"},
        incremental_fields=ACTIVITY_TIME_INCREMENTAL_FIELDS,
        partition_key="activityTime",
    ),
    "website_visits": CommonRoomEndpointConfig(
        name="website_visits",
        path="/website-visits",
        primary_keys=["id"],
        columns=WEBSITE_VISIT_COLUMNS,
        partition_key="visitTime",
    ),
    "segments": CommonRoomEndpointConfig(
        name="segments",
        path="/segments",
        primary_keys=["id"],
        columns=SEGMENT_COLUMNS,
    ),
    "tags": CommonRoomEndpointConfig(name="tags", path="/tags", primary_keys=["id"]),
    "topics": CommonRoomEndpointConfig(name="topics", path="/topics", primary_keys=["id"]),
    "providers": CommonRoomEndpointConfig(name="providers", path="/providers", primary_keys=["id"]),
    "custom_fields": CommonRoomEndpointConfig(
        name="custom_fields", path="/custom-fields", primary_keys=["id"], paginated=False
    ),
    "lead_scores": CommonRoomEndpointConfig(
        name="lead_scores", path="/lead-scores", primary_keys=["id"], paginated=False
    ),
    "activity_types": CommonRoomEndpointConfig(
        name="activity_types", path="/activity-types", primary_keys=["id"], paginated=False
    ),
    "activity_categories": CommonRoomEndpointConfig(
        name="activity_categories", path="/activity-categories", primary_keys=["id"], paginated=False
    ),
    "object_types": CommonRoomEndpointConfig(
        name="object_types", path="/object-types", primary_keys=["id"], paginated=False
    ),
    # `/objects` needs an `objectTypeId`, so the sync reads the object types first and lists the objects
    # of each type. The key holds the type id, because the docs do not say that object ids are unique
    # across types.
    "objects": CommonRoomEndpointConfig(
        name="objects",
        path="/objects",
        primary_keys=["objectTypeId", "id"],
        columns=OBJECT_COLUMNS,
        params={"sort": "id", "direction": "asc"},
        parent="object_types",
        resolve_param="objectTypeId",
    ),
    "activity_sentiment": CommonRoomEndpointConfig(
        name="activity_sentiment", path="/activity-sentiment", primary_keys=["id"], paginated=False
    ),
    # Job openings and news items are readable only per organization. The key holds the organization id,
    # because both come from a corpus keyed by company domain, so one posting or article can belong to
    # more than one organization.
    "job_openings": CommonRoomEndpointConfig(
        name="job_openings",
        path="/job-openings",
        primary_keys=["organizationId", "id"],
        page_size=500,
        columns=JOB_OPENING_COLUMNS,
        params={"sort": "firstSeenAt", "direction": "asc"},
        partition_key="firstSeenAt",
        parent="organizations",
        resolve_param="organizationId",
        resume_parent_pagination=True,
    ),
    "news_items": CommonRoomEndpointConfig(
        name="news_items",
        path="/news-items",
        primary_keys=["organizationId", "id"],
        params={"sort": "publishedAt", "direction": "asc"},
        partition_key="publishedAt",
        parent="organizations",
        resolve_param="organizationId",
        resume_parent_pagination=True,
    ),
}

ENDPOINTS = tuple(COMMON_ROOM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COMMON_ROOM_ENDPOINTS.items() if config.incremental_fields
}
