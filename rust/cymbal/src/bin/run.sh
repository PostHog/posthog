export KAFKA_CONSUMER_GROUP="cymbal"
export KAFKA_CONSUMER_TOPIC="exceptions_ingestion"
export OBJECT_STORAGE_BUCKET="posthog"
export OBJECT_STORAGE_ACCESS_KEY_ID="any"
export OBJECT_STORAGE_SECRET_ACCESS_KEY="any"
export FRAME_CACHE_TTL_SECONDS="1"
export ALLOW_INTERNAL_IPS="true"

RUST_LOG=debug,rdkafka=warn cargo run --bin cymbal
