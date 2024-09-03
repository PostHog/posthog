export PRINT_SINK="false"
export REDIS_URL="redis://localhost:6379"
export RUSTFLAGS="-C symbol-mangling-version=v0"
export KAFKA_HOSTS="localhost:9092"
export ADDRESS="127.0.0.1:3033"
export RUST_LOG="info"
export OTEL_URL="http://localhost:4317/v1/trace"
export KAFKA_PRODUCER_MESSAGE_MAX_BYTES="68000000" # A litte more than 1024*1024*64

export MEMORY_PROFILER_LOG=warn

LD_PRELOAD=../../bytehound/target/release/libbytehound.so ./target/debug/capture