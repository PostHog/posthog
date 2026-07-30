from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class OpenFDAEndpointConfig:
    name: str
    # Path under https://api.fda.gov, e.g. "/drug/enforcement.json".
    path: str
    primary_keys: list[str]
    # Server-side date field used both for incremental filtering (search=<field>:[low TO high]) and for
    # ascending sort. None means the endpoint has no reliable date cursor, so it ships full refresh only.
    incremental_field: Optional[str] = None
    # Stable date field to partition by. openFDA date fields record when the FDA received/created/posted
    # the record, so they don't move once written — safe partition keys. None disables partitioning.
    partition_key: Optional[str] = None
    should_sync_default: bool = True

    def build_incremental_fields(self) -> list[IncrementalField]:
        if self.incremental_field is None:
            return []
        return [
            {
                "label": self.incremental_field,
                "type": IncrementalFieldType.Date,
                "field": self.incremental_field,
                "field_type": IncrementalFieldType.Date,
            }
        ]


# openFDA exposes one endpoint per dataset, each with its own schema and date field. We surface the
# datasets a user is most likely to want across the drug, device, and food domains. Adverse-event and
# enforcement (recall) endpoints carry a genuine server-side date filter, so they sync incrementally;
# the NDC directory and drug labeling endpoints have no reliable row-level date cursor, so they ship
# full refresh only.
OPENFDA_ENDPOINTS: dict[str, OpenFDAEndpointConfig] = {
    "drug_events": OpenFDAEndpointConfig(
        name="drug_events",
        path="/drug/event.json",
        primary_keys=["safetyreportid"],
        incremental_field="receivedate",
        partition_key="receivedate",
    ),
    "drug_labels": OpenFDAEndpointConfig(
        name="drug_labels",
        path="/drug/label.json",
        primary_keys=["id"],
        # `effective_time` is frequently malformed (e.g. 9-digit values), so it can't anchor an
        # incremental watermark — full refresh only.
        incremental_field=None,
        partition_key=None,
        should_sync_default=False,
    ),
    "drug_ndc": OpenFDAEndpointConfig(
        name="drug_ndc",
        path="/drug/ndc.json",
        primary_keys=["product_id"],
        # The NDC directory is a current-state snapshot with no per-record date — full refresh only.
        incremental_field=None,
        partition_key=None,
    ),
    "drug_enforcement": OpenFDAEndpointConfig(
        name="drug_enforcement",
        path="/drug/enforcement.json",
        primary_keys=["recall_number"],
        incremental_field="report_date",
        partition_key="report_date",
    ),
    "device_events": OpenFDAEndpointConfig(
        name="device_events",
        path="/device/event.json",
        primary_keys=["mdr_report_key"],
        incremental_field="date_received",
        partition_key="date_received",
    ),
    "device_510k": OpenFDAEndpointConfig(
        name="device_510k",
        path="/device/510k.json",
        primary_keys=["k_number"],
        incremental_field="decision_date",
        partition_key="decision_date",
    ),
    "device_enforcement": OpenFDAEndpointConfig(
        name="device_enforcement",
        path="/device/enforcement.json",
        primary_keys=["recall_number"],
        incremental_field="report_date",
        partition_key="report_date",
    ),
    "food_enforcement": OpenFDAEndpointConfig(
        name="food_enforcement",
        path="/food/enforcement.json",
        primary_keys=["recall_number"],
        incremental_field="report_date",
        partition_key="report_date",
    ),
    "food_events": OpenFDAEndpointConfig(
        name="food_events",
        path="/food/event.json",
        primary_keys=["report_number"],
        incremental_field="date_created",
        partition_key="date_created",
    ),
}

ENDPOINTS = tuple(OPENFDA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.build_incremental_fields() for name, config in OPENFDA_ENDPOINTS.items()
}
