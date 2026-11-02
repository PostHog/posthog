from dataclasses import dataclass

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

RIDB_BASE_URL = "https://ridb.recreation.gov/api/v1"

# RIDB caps the `limit` query param at 50 records per page.
PAGE_LIMIT = 50

RESERVATIONS_ENDPOINT = "Reservations"
# `/reservations` requires a date range. A full refresh, or the first incremental sync, reads this far back.
RESERVATIONS_LOOKBACK_DAYS = 365
# The spec does not say which reservation date `dateFrom`/`dateTo` filter on. An end date in the
# future keeps new orders for future stays in range if the filter is on the stay dates.
RESERVATIONS_FORWARD_DAYS = 2 * 365


@dataclass(frozen=True)
class NestedRowsConfig:
    """Rows taken from an array that every parent row embeds, one table row per array item."""

    field: str
    parent_id_field: str


@dataclass(frozen=True)
class RecreationEndpointConfig:
    name: str
    path: str
    primary_key: str
    # Stable creation timestamp for datetime partitioning. Most RIDB entities only expose
    # LastUpdatedDate, which changes over time and is unsafe as a partition key.
    partition_key: str | None = None
    # The parent list embeds the same rows as the per-parent `/{id}/attributes` and `/{id}/zones`
    # endpoints, so reading them from the list avoids one request per parent row.
    nested: NestedRowsConfig | None = None


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
        path="/permitentrances",
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
    "CampsiteAttributes": RecreationEndpointConfig(
        name="CampsiteAttributes",
        path="/campsites",
        primary_key="AttributeName",
        nested=NestedRowsConfig(field="ATTRIBUTES", parent_id_field="CampsiteID"),
    ),
    "PermitEntranceAttributes": RecreationEndpointConfig(
        name="PermitEntranceAttributes",
        path="/permitentrances",
        primary_key="AttributeName",
        nested=NestedRowsConfig(field="ATTRIBUTES", parent_id_field="PermitEntranceID"),
    ),
    "PermitEntranceZones": RecreationEndpointConfig(
        name="PermitEntranceZones",
        path="/permitentrances",
        primary_key="PermitEntranceZoneID",
        nested=NestedRowsConfig(field="ZONES", parent_id_field="PermitEntranceID"),
    ),
    "TourAttributes": RecreationEndpointConfig(
        name="TourAttributes",
        path="/tours",
        primary_key="AttributeName",
        nested=NestedRowsConfig(field="ATTRIBUTES", parent_id_field="TourID"),
    ),
    RESERVATIONS_ENDPOINT: RecreationEndpointConfig(
        name=RESERVATIONS_ENDPOINT,
        path="/reservations",
        primary_key="HistoricalReservationID",
    ),
}

ENDPOINTS = tuple(RECREATION_ENDPOINTS.keys())

# Apart from the `/reservations` date range, the synced RIDB list endpoints have no server-side
# timestamp filter (query params cover state/activity/keyword/radius only), so they are full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    RESERVATIONS_ENDPOINT: [
        {
            "label": "OrderDate",
            "type": IncrementalFieldType.Date,
            "field": "OrderDate",
            "field_type": IncrementalFieldType.Date,
        }
    ],
}
