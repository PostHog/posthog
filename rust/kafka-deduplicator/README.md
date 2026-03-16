# Kafka deduplicator

Rust service for partition-aware Kafka event deduplication backed by RocksDB.

## Overview

The service consumes a Kafka topic, maintains per-partition deduplication state in local RocksDB stores, and optionally publishes results to downstream Kafka topics.

Today it supports two pipeline types:

- `ingestion_events`
- `clickhouse_events`

The default pipeline is `ingestion_events`.

## Consumer modes

The service supports two assignment models:

1. Group-based consumer mode

- Uses Kafka's consumer group protocol
- Handles partition assignment and revocation through the rebalance handler
- Imports checkpoints on assignment when enabled

2. Assigner-driven mode

- Enabled with `KAFKA_ASSIGNER_ENDPOINT`
- Uses the `kafka-assigner` service for partition assignment
- Supports warm handoff by importing checkpoints before taking ownership

## State model

- Deduplication state is isolated per Kafka partition
- Each partition store lives under `STORE_PATH`
- Checkpoint imports restore directly into timestamped store directories beneath the store path
- Local checkpoint staging lives under `LOCAL_CHECKPOINT_DIR`

The service also runs store cleanup logic to enforce `MAX_STORE_CAPACITY` and remove stale directories when safe.

## Output behavior

For the `ingestion_events` pipeline:

- `OUTPUT_TOPIC` is optional
- if `OUTPUT_TOPIC` is unset, events are still consumed and deduplicated, but nothing is forwarded
- `DUPLICATE_EVENTS_TOPIC` is optional and only applies to the ingestion-events pipeline

For the `clickhouse_events` pipeline:

- there is no duplicate-events topic configuration
- fail-open still bypasses deduplication logic for the pipeline

## Checkpoint system

Checkpointing is used for recovery and reassignment.

### Export

When checkpoint export is enabled, the checkpoint manager periodically:

1. creates a local RocksDB checkpoint for an owned partition
2. builds a checkpoint plan from the local checkpoint directory
3. uploads the required files plus metadata to remote object storage
4. removes the temporary local checkpoint directory

Incremental exports reuse previously uploaded `.sst` files when possible.
`CURRENT` is always re-uploaded.
Other mutable files such as `MANIFEST-*`, `OPTIONS-*`, and `.log` files are re-uploaded when their contents change.

### Import

When checkpoint import is enabled, assignment-time recovery:

1. lists recent checkpoint metadata files for the partition
2. downloads metadata lazily, newest first
3. downloads the referenced checkpoint files into a fresh local store directory
4. restores the imported directory as the active RocksDB store

If import fails, the service falls back to creating an empty store for the partition.

### Rebalance behavior

Rebalances suppress export work so imports get priority.

Workers now check the rebalance/export-suppression token:

- before local checkpoint creation
- around checkpoint planning
- during upload via the uploader's existing cancellation points

This means export may be skipped before upload even after a local checkpoint has already been created.

## Checkpoint configuration

Checkpoint import and export are gated by both feature flags and remote storage configuration.
Setting `CHECKPOINT_EXPORT_ENABLED=true` or `CHECKPOINT_IMPORT_ENABLED=true` is not enough by itself; the service also requires:

- `S3_BUCKET`
- either `AWS_REGION` or `S3_ENDPOINT`

Important checkpoint-related env vars:

| Variable | Description | Default |
|----------|-------------|---------|
| `CHECKPOINT_INTERVAL_SECS` | Time between checkpoint submission cycles | `1800` |
| `MAX_CONCURRENT_CHECKPOINTS` | Max in-flight checkpoint attempts per pod | `8` |
| `LOCAL_CHECKPOINT_DIR` | Local checkpoint staging directory | `/tmp/local_checkpoints` |
| `CHECKPOINT_FULL_UPLOAD_INTERVAL` | Full-upload cadence; `0` means always full | `0` |
| `CHECKPOINT_IMPORT_ENABLED` | Enable checkpoint import | `false` |
| `CHECKPOINT_EXPORT_ENABLED` | Enable checkpoint export | `false` |
| `CHECKPOINT_IMPORT_ATTEMPT_DEPTH` | Number of recent checkpoints to try on import | `10` |
| `CHECKPOINT_IMPORT_WINDOW_HOURS` | Recovery search window | `24` |
| `MAX_CONCURRENT_CHECKPOINT_FILE_DOWNLOADS` | Max concurrent S3 file downloads during import | `200` |
| `MAX_CONCURRENT_CHECKPOINT_FILE_UPLOADS` | Max concurrent S3 file uploads during export | `200` |
| `CHECKPOINT_PARTITION_IMPORT_TIMEOUT_SECS` | End-to-end import timeout per partition | `240` |
| `S3_OPERATION_TIMEOUT_SECS` | Total S3 op timeout including retries | `120` |
| `S3_ATTEMPT_TIMEOUT_SECS` | Per-attempt S3 timeout | `20` |
| `S3_MAX_RETRIES` | S3 retry count | `3` |
| `S3_KEY_PREFIX` | Remote checkpoint prefix | `deduplication-checkpoints` |

## Fail-open mode

`FAIL_OPEN=true` is the emergency bypass.

When enabled, the service:

- bypasses deduplication logic
- skips RocksDB store usage
- skips checkpoint import/export and cleanup infrastructure
- treats all events as unique

This is intended as an operational kill switch when the deduplication subsystem is causing problems.

## Selected runtime configuration

### Kafka

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_HOSTS` | Kafka bootstrap servers | `localhost:9092` |
| `KAFKA_CONSUMER_GROUP` | Consumer group ID | `kafka-deduplicator` |
| `KAFKA_CONSUMER_TOPIC` | Source topic | `events` |
| `KAFKA_TLS` | Enable TLS for Kafka | `false` |
| `KAFKA_MAX_POLL_INTERVAL_MS` | Max time between poll calls | `300000` |

### Pipeline / outputs

| Variable | Description | Default |
|----------|-------------|---------|
| `PIPELINE_TYPE` | `ingestion_events` or `clickhouse_events` | `ingestion_events` |
| `OUTPUT_TOPIC` | Topic for forwarded unique events | unset |
| `DUPLICATE_EVENTS_TOPIC` | Topic for duplicate-event publishing in ingestion-events pipeline | unset |

### Storage

| Variable | Description | Default |
|----------|-------------|---------|
| `STORE_PATH` | Base path for RocksDB stores | `/tmp/deduplication-store` |
| `MAX_STORE_CAPACITY` | Capacity limit per store manager config; accepts raw bytes or units like `Gi` | `1073741824` |
| `CLEANUP_INTERVAL_SECS` | Capacity cleanup interval | `120` |
| `ORPHAN_CLEANUP_MIN_STALENESS_SECS` | Minimum staleness before orphan cleanup | `900` |
| `REBALANCE_CLEANUP_PARALLELISM` | Max parallel directory deletions during rebalance cleanup | `16` |

### RocksDB tuning

The service exposes env overrides for RocksDB tuning and otherwise falls back to compiled defaults from `RocksDbConfig`.

Common overrides include:

- `ROCKSDB_SHARED_CACHE_SIZE_BYTES`
- `ROCKSDB_TOTAL_WRITE_BUFFER_SIZE_BYTES`
- `ROCKSDB_MAX_BACKGROUND_JOBS`
- `ROCKSDB_WRITE_BUFFER_SIZE_BYTES`
- `ROCKSDB_TARGET_FILE_SIZE_BASE_BYTES`
- `ROCKSDB_MAX_OPEN_FILES`
- `ROCKSDB_L0_COMPACTION_TRIGGER`
- `ROCKSDB_L0_SLOWDOWN_WRITES_TRIGGER`
- `ROCKSDB_L0_STOP_WRITES_TRIGGER`
- `ROCKSDB_WRITE_BUFFER_MANAGER_ALLOW_STALL`

## Health and metrics

The binary serves:

- `/_readiness`
- `/_liveness`
- `/metrics` when `EXPORT_PROMETHEUS=true`

Prometheus export is enabled by default.

## Main components

- `KafkaDeduplicatorService`
- `BatchConsumer`
- `AssignerConsumer`
- `ProcessorRebalanceHandler`
- `StoreManager`
- `CheckpointManager`
- `CheckpointImporter`
- `CheckpointExporter`

## Testing

```bash
# Run all tests
cargo test

# Run a specific integration suite
cargo test --test checkpoint_integration_tests
cargo test --test checkpoint_tests
cargo test --test batch_consumer_integration_tests
cargo test --test rebalance_e2e_integration_tests
```
