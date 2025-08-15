# Kafka Deduplicator

A high-performance Rust service for real-time event deduplication in Kafka streams.

## Overview

The Kafka Deduplicator consumes events from a Kafka topic, removes duplicates using RocksDB for persistent storage, and publishes unique events to an output topic.

## How the Kafka Consumer Works

### Stateful Consumer Architecture

The Kafka consumer is built as a stateful, partition-aware consumer that maintains processing state across rebalances. Key characteristics:

- **Per-partition state management**: Each Kafka partition gets its own isolated deduplication store, allowing horizontal scaling
- **Message tracking**: Tracks in-flight messages to ensure exactly-once processing semantics
- **Graceful rebalancing**: During partition reassignment, the consumer:
  - Waits for all in-flight messages from revoked partitions to complete
  - Cleanly shuts down partition-specific stores
  - Initializes new stores for newly assigned partitions
- **Offset management**: Commits offsets only after messages are successfully processed, preventing data loss

### Partition Handling

When partitions are assigned or revoked (during rebalancing):

1. **Partition Assignment**: Creates a new RocksDB store for each assigned partition at path: `{base_path}/{topic}_{partition}/`
2. **Partition Revocation**: 
   - Marks the partition as "fenced" to reject new messages
   - Waits for in-flight messages to complete
   - Cleanly closes the RocksDB store
3. **Isolation**: Each partition's deduplication state is completely isolated, preventing cross-partition interference

### Message Flow

1. Consumer polls messages from Kafka
2. Each message is wrapped in an `AckableMessage` for explicit acknowledgment
3. Messages are processed with configurable concurrency limits
4. After processing, messages are explicitly acknowledged (ack/nack)
5. Offsets are committed only for successfully processed messages

## Deduplication Strategy

Events are deduplicated based on a **composite key**:
- Format: `timestamp:distinct_id:token:event_name`
- Two events with the same composite key are considered duplicates
- UUID is used only for Kafka partitioning, not deduplication

## Architecture Components

- **StatefulKafkaConsumer**: Main consumer orchestrating message processing
- **MessageTracker**: Tracks in-flight messages and manages offset completion
- **RebalanceHandler**: Handles partition assignment/revocation during rebalancing
- **Per-partition RocksDB stores**: Isolated storage for each partition's deduplication state

## Configuration

### Kafka Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_HOSTS` | Kafka bootstrap servers | `localhost:9092` |
| `KAFKA_CONSUMER_GROUP` | Consumer group ID | `kafka-deduplicator` |
| `KAFKA_CONSUMER_TOPIC` | Source topic | `events` |
| `OUTPUT_TOPIC` | Destination topic for unique events | Optional |
| `MAX_IN_FLIGHT_MESSAGES` | Max concurrent messages | `1000` |

### Storage Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `STORE_PATH` | Base path for RocksDB stores | `/tmp/deduplication-store` |
| `MAX_STORE_CAPACITY` | Max storage per partition (bytes) | `0` (unlimited) |

## Testing

```bash
# Run all tests
cargo test

# Run Kafka integration tests (requires Kafka running)
cargo test --test kafka_integration_tests
```