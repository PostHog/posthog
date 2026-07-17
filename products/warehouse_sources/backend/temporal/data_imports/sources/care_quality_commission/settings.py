from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class CQCEndpointConfig:
    name: str
    # List endpoint returning summary records + pagination metadata (e.g. "/providers").
    list_path: str
    # Key under which the list endpoint nests its records (e.g. "providers").
    list_data_key: str
    # Per-record id field on the summary record (e.g. "providerId").
    id_field: str
    # Detail endpoint template fetched per id for the full record (e.g. "/providers/{id}").
    detail_path: str
    # Required, no default: each endpoint has its own key (providerId vs locationId), so a generic
    # default would silently mis-key any future endpoint that forgot to set it.
    primary_keys: list[str]
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
        id_field="providerId",
        detail_path="/providers/{id}",
        primary_keys=["providerId"],
    ),
    "locations": CQCEndpointConfig(
        name="locations",
        list_path="/locations",
        list_data_key="locations",
        id_field="locationId",
        detail_path="/locations/{id}",
        primary_keys=["locationId"],
    ),
}

ENDPOINTS = tuple(CQC_ENDPOINTS.keys())

# Both endpoints ship full-refresh only. The CQC API exposes change detection solely through the
# dedicated /changes/provider and /changes/location endpoints, which return changed ids for a
# timestamp window — but the per-record detail returned by /providers/{id} and /locations/{id}
# carries no stable "last modified" column to anchor the pipeline's incremental watermark to, so a
# reliable server-side incremental cursor isn't available. See the module docstring in
# care_quality_commission.py for the full rationale.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CQC_ENDPOINTS.items()
}
