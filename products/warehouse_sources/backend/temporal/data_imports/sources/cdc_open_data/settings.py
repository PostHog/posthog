"""Endpoint catalog and constants for the CDC Open Data (Socrata SODA) connector.

CDC Open Data (data.cdc.gov) publishes every dataset behind the same generic Socrata SODA REST
API rather than a fixed set of named endpoints, so "endpoints" here means the dataset 4x4 IDs
the user configures, not a vendor-defined catalog.
"""

import re

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CDC_BASE_URL = "https://data.cdc.gov"

# Socrata assigns every dataset a "4x4" identifier: two 4-character alphanumeric groups joined
# by a hyphen (e.g. "9bhg-hcku"), visible in the dataset's data.cdc.gov URL.
DATASET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9]{4}-[a-zA-Z0-9]{4}$")

# Caps how many datasets a single source can fan out into. Each configured ID becomes its own
# schema, database row, and Temporal schedule, so this bounds setup-time resource usage rather
# than any vendor-side limit.
MAX_DATASET_IDS = 50

# Socrata system fields present on every dataset regardless of its own columns. Only returned
# when `$$exclude_system_fields=false` is sent (see cdc_open_data.py).
SOCRATA_ID_FIELD = ":id"
SOCRATA_UPDATED_AT_FIELD = ":updated_at"

# SODA 2.0 endpoints cap $limit at 50,000; 2.1/3.0 are unbounded. 10k keeps each page's JSON
# payload (and in-memory parse) modest for wide datasets while still bounding round trips.
PAGE_SIZE = 10_000

# `:updated_at` is the only field guaranteed to exist and be filterable on every dataset,
# regardless of the dataset's own columns, so it's the sole incremental candidate offered.
# A full-table republish (common on CDC's surveillance datasets) bumps `:updated_at` on every
# row, so an incremental sync after a republish re-fetches the whole dataset via merge rather
# than missing anything.
INCREMENTAL_FIELDS: list[IncrementalField] = [
    incremental_field(
        field=SOCRATA_UPDATED_AT_FIELD,
        field_type=IncrementalFieldType.DateTime,
        label="Last updated (:updated_at)",
    ),
]


def parse_dataset_ids(raw: str) -> list[str]:
    """Split the user-entered dataset IDs field into a deduplicated, order-preserving list."""
    seen: set[str] = set()
    dataset_ids: list[str] = []
    for token in re.split(r"[,\n]+", raw or ""):
        dataset_id = token.strip()
        if dataset_id and dataset_id not in seen:
            seen.add(dataset_id)
            dataset_ids.append(dataset_id)
    return dataset_ids
