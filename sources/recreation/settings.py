from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField

RIDB_BASE_URL = "https://ridb.recreation.gov/api/v1"

# RIDB caps the `limit` query param at 50 records per page.
PAGE_LIMIT = 50


@dataclass(frozen=True)
class RecreationEndpointConfig:
    name: str
    path: str
    primary_key: str
    # Stable creation timestamp for datetime partitioning. Most RIDB entities only expose
    # LastUpdatedDate, which changes over time and is unsafe as a partition key.
    partition_key: str | None = None


RECREATION_ENDPOINTS: dict[str, RecreationEndpointConfig] = {
    "Activities": RecreationEndpointConfig(
        name="Activities",
        path="/activities",
        primary_key="ActivityID",
    ),
    "Campsites": RecreationEndpointConfig(
        name="Campsites",
        path="/campsites",
        primary_key="CampsiteID",
        partition_key="CreatedDate",
    ),
    "Events": RecreationEndpointConfig(
        name="Events",
        path="/events",
        primary_key="EventID",
    ),
    "Facilities": RecreationEndpointConfig(
        name="Facilities",
        path="/facilities",
        primary_key="FacilityID",
    ),
    "FacilityAddresses": RecreationEndpointConfig(
        name="FacilityAddresses",
        path="/facilityaddresses",
        primary_key="FacilityAddressID",
    ),
    "Links": RecreationEndpointConfig(
        name="Links",
        path="/links",
        primary_key="EntityLinkID",
    ),
    "Media": RecreationEndpointConfig(
        name="Media",
        path="/media",
        primary_key="EntityMediaID",
    ),
    "Organizations": RecreationEndpointConfig(
        name="Organizations",
        path="/organizations",
        primary_key="OrgID",
    ),
    "PermitEntrances": RecreationEndpointConfig(
        name="PermitEntrances",
        path="/permits",
        primary_key="PermitEntranceID",
        partition_key="CreatedDate",
    ),
    "RecAreas": RecreationEndpointConfig(
        name="RecAreas",
        path="/recareas",
        primary_key="RecAreaID",
    ),
    "RecAreaAddresses": RecreationEndpointConfig(
        name="RecAreaAddresses",
        path="/recareaaddresses",
        primary_key="RecAreaAddressID",
    ),
    "Tours": RecreationEndpointConfig(
        name="Tours",
        path="/tours",
        primary_key="TourID",
        partition_key="CreatedDate",
    ),
}

ENDPOINTS = tuple(RECREATION_ENDPOINTS.keys())

# RIDB has no server-side timestamp filter on any list endpoint (query params cover
# state/activity/keyword/radius only), so every endpoint is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
