export PRINT_SINK="true"
export REDIS_URL="redis://localhost:6379"
export RUSTFLAGS="-C symbol-mangling-version=v0"
export KAFKA_HOSTS="kafka:9092"
export ADDRESS="127.0.0.1:3033"
export RUST_LOG="debug"

export KAFKA_PRODUCER_MESSAGE_MAX_BYTES="68000000" # A litte more than 1024*1024*64

cargo instruments -t Allocations --package capture --bin capture