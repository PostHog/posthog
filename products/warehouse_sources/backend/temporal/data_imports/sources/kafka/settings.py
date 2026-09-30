from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

TOPIC_COLUMN = "_kafka_topic"
PARTITION_COLUMN = "_kafka_partition"
OFFSET_COLUMN = "_kafka_offset"
TIMESTAMP_COLUMN = "_kafka_timestamp"
TIMESTAMP_MS_COLUMN = "_kafka_timestamp_ms"
KEY_COLUMN = "_kafka_key"
KEY_ENCODING_COLUMN = "_kafka_key_encoding"
HEADERS_COLUMN = "_kafka_headers"
TOMBSTONE_COLUMN = "_kafka_tombstone"
# Holds a JSON-format message whose value does not parse, so one bad message does not fail the sync.
RAW_VALUE_COLUMN = "_kafka_raw_value"
RAW_VALUE_ENCODING_COLUMN = "_kafka_raw_value_encoding"
# Holds a value that is not a JSON object, and every value of a text-format topic.
VALUE_COLUMN = "value"
VALUE_ENCODING_COLUMN = "_kafka_value_encoding"

# A partition and an offset name one message of one topic, and each topic is its own table.
PRIMARY_KEYS = [PARTITION_COLUMN, OFFSET_COLUMN]

# The offset cursor decides where a run starts. The timestamp is offered as the incremental field
# because incremental syncs need one, and its maximum shows how far the table has caught up.
INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": TIMESTAMP_COLUMN,
        "type": IncrementalFieldType.DateTime,
        "field": TIMESTAMP_COLUMN,
        "field_type": IncrementalFieldType.DateTime,
    }
]

# Kafka and Confluent Platform name their internal topics with a leading underscore
# (`__consumer_offsets`, `__transaction_state`, `_schemas`, `_confluent-*`).
INTERNAL_TOPIC_PREFIX = "_"

CLIENT_ID = "posthog-data-warehouse"
METADATA_TIMEOUT_SECONDS = 15
WATERMARK_TIMEOUT_SECONDS = 15
CONSUME_BATCH_SIZE = 1000
CONSUME_TIMEOUT_SECONDS = 1.0
# A partition that stops delivering before its end offset is waiting on an open transaction, which
# hides the messages after it from a read_committed consumer. The run stops waiting after this long
# and the next run continues from the partition's position.
IDLE_TIMEOUT_SECONDS = 60.0
