from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Newest version Microsoft lists for the Cosmos DB REST API; sent as `x-ms-version` on every call.
API_VERSION = "2018-12-31"
PAGE_SIZE = 500
# Written on every row: the document's partition key value, so `id` (unique only within a logical
# partition) becomes a table-wide key with it.
PARTITION_KEY_COLUMN = "_partition_key"
PRIMARY_KEYS = ["id", PARTITION_KEY_COLUMN]
# Cosmos stamps `_ts` (epoch seconds) on every write, so it is the one server-side cursor every
# container has.
TIMESTAMP_FIELD = "_ts"
INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": TIMESTAMP_FIELD,
        "type": IncrementalFieldType.Integer,
        "field": TIMESTAMP_FIELD,
        "field_type": IncrementalFieldType.Integer,
        "is_indexed": True,
    }
]
