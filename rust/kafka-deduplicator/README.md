# Kafka Deduplicator

A high-performance Rust service for real-time event deduplication in Kafka streams.

## What it does

The Kafka Deduplicator consumes events from a Kafka topic, removes duplicates, and publishes unique events to an output topic. It uses RocksDB for persistent deduplication storage with per-partition stores for horizontal scalability.

We want to use this service to deduplicate events from the `events` topic.

As a first step, we want to expose a series of metrics surrounding the deduplication issue.

For each duplicate event based on the composite key, we want to expose the following metrics:
- The number of duplicate events for that composite key
- The similarity score of the duplicate events
- The similarity score of the properties of the duplicate events
- How many unique uuids with the same composite key are there and how similar are they to the original
- Which properties change between the original and the duplicate events
- Which properties are the same between the original and the duplicate events

## Deduplication Strategy

### Composite Key Deduplication
Events are deduplicated based on a **composite key** consisting of:
- `timestamp`
- `distinct_id` 
- `token`
- `event_name`

The key format is: `timestamp:distinct_id:token:event_name`

This means two events with the same timestamp, distinct_id, token, and event_name will be considered duplicates, regardless of other fields.

### UUID vs Content-based Kafka Keys
While deduplication always uses the composite key above, the service handles Kafka message keys differently:

- **Events with UUID**: Use the UUID as the Kafka message key (for partitioning)

Note: The UUID does **not** affect deduplication logic - it's only used for Kafka partitioning.

## Example

These two events would be considered **duplicates** (same composite key):
```json
// Event 1 - with UUID
{
  "uuid": "123e4567-e89b-12d3-a456-426614174000",
  "event": "page_view",
  "distinct_id": "user123",
  "token": "phc_abc123",
  "timestamp": "1640995200"
}

// Event 2 - different UUID but same composite key fields
{
  "uuid": "987e6543-e89b-12d3-a456-426614174000",  
  "event": "page_view",
  "distinct_id": "user123",
  "token": "phc_abc123",
  "timestamp": "1640995200"
}
```

## Architecture

- **Per-partition RocksDB stores**: Each Kafka partition gets its own deduplication store
- **Batch processing**: Groups operations for better throughput
- **Graceful rebalancing**: Cleans up partition stores when reassigned
- **Automatic cleanup**: Removes old entries when storage limits are reached

## Configuration

Configuration uses PostHog's `envconfig` pattern with environment variables:

### Kafka Consumer Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_HOSTS` | Kafka bootstrap servers | `localhost:9092` |
| `KAFKA_CONSUMER_GROUP` | Kafka consumer group | `kafka-deduplicator` |
| `KAFKA_CONSUMER_TOPIC` | Source topic to consume from | `events` |
| `KAFKA_CONSUMER_OFFSET_RESET` | Offset reset strategy | `earliest` |
| `KAFKA_CONSUMER_AUTO_COMMIT` | Enable auto offset commits | `false` |

### Kafka Producer Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_PRODUCER_LINGER_MS` | Max time between batches | `20` |
| `KAFKA_PRODUCER_QUEUE_MIB` | Producer queue size (MiB) | `400` |
| `KAFKA_PRODUCER_QUEUE_MESSAGES` | Max messages in queue | `10000000` |
| `KAFKA_MESSAGE_TIMEOUT_MS` | Message timeout | `20000` |
| `KAFKA_COMPRESSION_CODEC` | Compression type | `snappy` |
| `OUTPUT_TOPIC` | Destination topic for unique events | Optional |

### Storage Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `STORE_PATH` | RocksDB storage directory | `/tmp/deduplication-store` |
| `MAX_STORE_CAPACITY` | Storage limit per partition (bytes) | `1073741824` (1GB) |

### Consumer Processing Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `MAX_IN_FLIGHT_MESSAGES` | Total concurrent messages | `100` |
| `MAX_IN_FLIGHT_MESSAGES_PER_PARTITION` | Per-partition concurrent messages | `100` |
| `MAX_MEMORY_BYTES` | Max memory for in-flight messages | `67108864` (64MB) |
| `WORKER_THREADS` | Number of worker threads | `4` |
| `POLL_TIMEOUT_SECS` | Kafka poll timeout | `1` |
| `SHUTDOWN_TIMEOUT_SECS` | Graceful shutdown timeout | `30` |

### HTTP Server Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `BIND_HOST` | HTTP server bind host | `0.0.0.0` |
| `BIND_PORT` | HTTP server bind port | `8080` |

### Checkpoint Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `CHECKPOINT_INTERVAL_SECS` | Checkpoint frequency | `300` (5 minutes) |
| `LOCAL_CHECKPOINT_DIR` | Local checkpoint directory | `./checkpoints` |
| `S3_BUCKET` | S3 bucket for checkpoints | Optional |
| `S3_KEY_PREFIX` | S3 key prefix | `deduplication-checkpoints` |
| `FULL_UPLOAD_INTERVAL` | Full upload frequency | `10` |
| `AWS_REGION` | AWS region | `us-east-1` |
| `MAX_LOCAL_CHECKPOINTS` | Max local checkpoints to keep | `5` |
| `S3_TIMEOUT_SECS` | S3 operation timeout | `300` (5 minutes) |

## Metrics Endpoint

The service exposes a Prometheus-compatible metrics endpoint following PostHog's standard pattern.

Available endpoints:
- **`/`**: Service status
- **`/_readiness`**: Readiness check
- **`/_liveness`**: Liveness check  
- **`/metrics`**: Prometheus metrics

Available metrics include:
- **HTTP request metrics**: Request count, latency, and status codes
- **Deduplication metrics**: Duplicate counts, property similarity scores, and processing statistics
- **Store metrics**: Memory usage, processing counts per partition

Example:
```bash
curl http://localhost:8080/metrics
```

## Running

```bash
export INPUT_TOPIC="raw-events"
export OUTPUT_TOPIC="deduplicated-events"
cargo run --release
```

## How it works

1. **Consume**: Read events from input topic
2. **Extract composite key**: Build key from `timestamp:distinct_id:token:event_name`
3. **Check store**: Look up composite key in partition-specific RocksDB store
4. **Deduplicate**: 
   - If composite key exists: Drop as duplicate
   - If composite key is new: Store key and forward event to output topic
5. **Cleanup**: Periodically remove old entries to manage storage size

## Performance

- **Throughput**: ~50K events/sec per partition
- **Latency**: P95 < 10ms end-to-end
- **Storage**: Automatic cleanup when capacity limits reached
- **Scaling**: Linear with number of partitions

## Testing

```bash
# Unit tests
cargo test --lib

# Integration tests (requires Kafka running on localhost:9092)
cargo test
```
