from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField


@frozen
class CQCEndpointConfig:
    name: str
    # List endpoint returning the rows, or the summary records to fan out from (e.g. "/providers").
    list_path: str
    # Key under which the list endpoint nests its records (e.g. "providers").
    list_data_key: str
    # Required, no default: each endpoint has its own key (providerId vs locationId), so a generic
    # default would silently mis-key any future endpoint that forgot to set it.
    primary_keys: list[str]
    # Per-record id field on the summary record (e.g. "providerId"). Set together with
    # `detail_path`; both stay None when the list records are already the full rows.
    id_field: Optional[str] = None
    # Detail endpoint template fetched per id (e.g. "/providers/{id}").
    detail_path: Optional[str] = None
    # Key under which the detail endpoint nests a list of rows. None means the detail body is
    # itself a single row.
    detail_data_key: Optional[str] = None
    # Whether the list endpoint takes page/perPage. The inspection-area taxonomy returns the whole
    # table in one body and ignores paging, so asking for page 2 would re-serve page 1 forever.
    paginated: bool = True
    # Stable date field used for datetime partitioning. `registrationDate` is the date the
    # provider/location first registered with CQC — it never changes once set, unlike rating
    # or inspection dates which move on every re-inspection.
    partition_key: Optional[str] = "registrationDate"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


CQC_ENDPOINTS: dict[str, CQCEndpointConfig] = {
    "providers": CQCEndpointConfig(
        name="providers",
        list_path="/providers",
        list_data_key="providers",
        primary_keys=["providerId"],
        id_field="providerId",
        detail_path="/providers/{id}",
    ),
    "locations": CQCEndpointConfig(
        name="locations",
        list_path="/locations",
        list_data_key="locations",
        primary_keys=["locationId"],
        id_field="locationId",
        detail_path="/locations/{id}",
    ),
    "inspection_areas": CQCEndpointConfig(
        name="inspection_areas",
        list_path="/inspection-areas",
        list_data_key="inspectionAreas",
        primary_keys=["inspectionAreaId"],
        paginated=False,
        # Taxonomy rows carry no creation date — `endDate` and `orgInspectionAreaRetirementDate`
        # both move when CQC retires an area.
        partition_key=None,
    ),
    "provider_inspection_areas": CQCEndpointConfig(
        name="provider_inspection_areas",
        list_path="/providers",
        list_data_key="providers",
        primary_keys=["providerId", "inspectionAreaId"],
        id_field="providerId",
        detail_path="/providers/{id}/inspection-areas",
        detail_data_key="inspectionAreas",
        partition_key=None,
        # One request per registered provider, on top of whatever the `providers` stream already
        # costs, so let the user opt in rather than doubling every new connection's first sync.
        should_sync_default=False,
    ),
    "location_inspection_areas": CQCEndpointConfig(
        name="location_inspection_areas",
        list_path="/locations",
        list_data_key="locations",
        primary_keys=["locationId", "inspectionAreaId"],
        id_field="locationId",
        detail_path="/locations/{id}/inspection-areas",
        detail_data_key="inspectionAreas",
        partition_key=None,
        # CQC registers far more locations than providers, so this fan-out is the most expensive
        # stream of the set — off by default.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(CQC_ENDPOINTS.keys())

# Every endpoint ships full-refresh only. The CQC API exposes change detection solely through the
# dedicated /changes/provider and /changes/location endpoints, which return changed ids for a
# timestamp window — but the per-record detail returned by /providers/{id} and /locations/{id}
# carries no stable "last modified" column to anchor the pipeline's incremental watermark to, so a
# reliable server-side incremental cursor isn't available. See the module docstring in
# care_quality_commission.py for the full rationale.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CQC_ENDPOINTS.items()
}
