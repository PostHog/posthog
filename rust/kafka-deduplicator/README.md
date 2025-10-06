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

## Checkpoint System

The service includes a comprehensive checkpoint system for backup, recovery, and horizontal scaling:

### Checkpoint Strategy

- **Periodic snapshots**: Creates RocksDB checkpoints at configurable intervals (default: 5 minutes)
- **Point-in-time consistency**: Checkpoints capture the complete deduplication state at a specific moment
- **Multi-tier storage**: Local checkpoints for fast recovery, S3 uploads for durability and scaling
- **Incremental vs Full uploads**:
  - **Incremental**: Upload only changed SST files since last checkpoint
  - **Full**: Upload complete checkpoint (every N incremental uploads, default: 10)

### Checkpoint Components

- **CheckpointExporter**: Orchestrates checkpoint creation and upload process
- **CheckpointLoader**: Handles downloading and restoring checkpoints from remote storage  
- **S3Client**: Manages S3 operations for checkpoint storage and retrieval
- **Metadata tracking**: Records checkpoint info (timestamp, files, offsets, sizes)

### Checkpoint Flow

1. **Creation** (synchronous): RocksDB creates atomic snapshot with SST file tracking
2. **Upload** (asynchronous): Background upload to S3 with configurable timeouts and retries
3. **Cleanup** (asynchronous): Automatic removal of old local checkpoints (keeps N most recent)
4. **Recovery** (asynchronous): On startup, can restore from latest checkpoint to resume processing

### Async Operations

- **Checkpoint loop**: Runs continuously in background with configurable intervals
- **S3 uploads**: Non-blocking uploads prevent checkpoint creation from blocking message processing
- **Directory cleanup**: Old checkpoint removal happens asynchronously
- **Recovery downloads**: Checkpoint restoration from S3 is async and resumable

### Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `CHECKPOINT_INTERVAL` | Time between checkpoints | `300s` |
| `LOCAL_CHECKPOINT_DIR` | Local checkpoint storage path | `./checkpoints` |
| `S3_BUCKET` | S3 bucket for checkpoint uploads | (required) |
| `S3_KEY_PREFIX` | S3 key prefix for organization | `deduplication-checkpoints` |
| `FULL_UPLOAD_INTERVAL` | Incremental uploads before full | `10` |
| `MAX_LOCAL_CHECKPOINTS` | Local checkpoints to retain | `5` |

## Architecture Components

- **StatefulKafkaConsumer**: Main consumer orchestrating message processing
- **MessageTracker**: Tracks in-flight messages and manages offset completion
- **RebalanceHandler**: Handles partition assignment/revocation during rebalancing
- **Per-partition RocksDB stores**: Isolated storage for each partition's deduplication state
- **CheckpointExporter**: Creates and manages periodic snapshots for backup/recovery

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
