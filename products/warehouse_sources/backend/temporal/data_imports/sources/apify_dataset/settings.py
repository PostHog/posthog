from products.warehouse_sources.backend.types import IncrementalField

APIFY_BASE_URL = "https://api.apify.com/v2"

# Apify exposes the rows produced by an Actor run as a single dataset. The dataset is addressed by a
# datasetId (or the `username~dataset-name` shorthand) and queried via GET /datasets/{id}/items. The
# rows are arbitrary Actor output, so this source ships exactly one table whose columns are whatever
# the Actor stored.
DATASET_ITEMS_ENDPOINT = "dataset_items"

ENDPOINTS = (DATASET_ITEMS_ENDPOINT,)

# Dataset rows have no field the API guarantees to be present or unique (the shape is defined by the
# Actor, not Apify), so there is no primary key to merge on. Combined with the lack of a server-side
# timestamp filter, the table is full-refresh only and the whole dataset is replaced on every sync.
PRIMARY_KEYS: dict[str, list[str] | None] = {
    DATASET_ITEMS_ENDPOINT: None,
}

# No advertised incremental fields: dataset items are append-only with no server-side `updated_after`
# style filter, so an "incremental" sync would still page through every row. Ship full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    DATASET_ITEMS_ENDPOINT: [],
}
