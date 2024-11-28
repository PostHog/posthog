export KAFKA_CONSUMER_GROUP="cymbal"
export KAFKA_CONSUMER_TOPIC="exception_symbolification_events"
export OBJECT_STORAGE_BUCKET="posthog"
export OBJECT_STORAGE_ACCESS_KEY_ID="object_storage_root_user"
export OBJECT_STORAGE_SECRET_ACCESS_KEY="object_storage_root_password"
export ALLOW_INTERNAL_IPS="true"

RUST_LOG=info cargo run --bin cymbal
