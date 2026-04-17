# personhog-writer

Consumes person state updates from the `personhog_updates` Kafka topic and batch-upserts them to the `personhog_person` Postgres table, closing the durability loop between the personhog-leader's in-memory cache and persistent storage.

## Architecture

```text
personhog_updates (Kafka, compacted)
    │
    ▼
┌──────────────────────────────────────────┐
│  personhog-writer                     │
│                                          │
│  Consumer Task          Writer Task      │
│  ┌────────────┐        ┌─────────────┐   │
│  │ Kafka recv │        │ PG upsert   │   │
│  │ Proto decode│───────│ Offset commit│   │
│  │ Buffer dedup│ channel│ Backoff     │   │
│  └────────────┘        └─────────────┘   │
└──────────────────────────────────────────┘
    │
    ▼
personhog_person (Postgres, hash-partitioned)
```

The service runs two concurrent tokio tasks connected by a bounded channel:

- **Consumer task**: reads from Kafka, decodes Person protobuf messages, deduplicates in an in-memory buffer keyed by (team_id, person_id), and sends batches to the writer task on flush triggers.
- **Writer task**: receives batches, upserts to Postgres via `INSERT ... ON CONFLICT`, and commits Kafka offsets only after a successful write.

## Flush triggers

The consumer flushes the buffer when any of these conditions are met:

- **Timer**: every `FLUSH_INTERVAL_MS` (default 5s)
- **Size threshold**: buffer reaches `FLUSH_BUFFER_SIZE` entries (default 1000)
- **Backpressure**: buffer reaches `BUFFER_CAPACITY` (default 50k), flush immediately
- **Shutdown**: graceful shutdown flushes remaining buffer

## Idempotency

The upsert includes `WHERE EXCLUDED.version > personhog_person.version`, so out-of-order or replayed messages from Kafka are safely ignored. This makes crash recovery simple: uncommitted offsets cause Kafka to redeliver, and the version guard prevents duplicate writes.

## Backpressure

When the writer is slow (PG latency, connection pool exhaustion), the bounded channel between consumer and writer fills up. The consumer blocks on channel send, which stops Kafka consumption. This naturally limits memory usage and prevents unbounded buffering.

If Postgres fails 3 consecutive times, the service signals unhealthy and shuts down, relying on K8s to restart it with CrashLoopBackOff providing exponential retry spacing.

## Kafka consumer configuration

- **Cooperative-sticky assignment**: during autoscaling, only partitions that need to move are revoked
- **Static group membership**: when `KAFKA_CLIENT_ID` is set, the broker holds partition assignments during pod restarts (requires StatefulSet for stable pod names)
- **Manual offset commits**: offsets are committed only after a successful Postgres write

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_HOSTS` | `localhost:9092` | Kafka bootstrap servers |
| `KAFKA_TLS` | `false` | Enable TLS for Kafka |
| `KAFKA_CLIENT_ID` | (empty) | Pod name for static group membership |
| `KAFKA_TOPIC` | `personhog_updates` | Topic to consume |
| `KAFKA_CONSUMER_GROUP` | `personhog-writer` | Consumer group ID |
| `KAFKA_CONSUMER_OFFSET_RESET` | `earliest` | Offset reset policy |
| `DATABASE_URL` | (required) | Postgres connection string |
| `PG_MAX_CONNECTIONS` | `10` | Connection pool size |
| `FLUSH_INTERVAL_MS` | `5000` | Timer-based flush interval |
| `FLUSH_BUFFER_SIZE` | `1000` | Size-based flush trigger |
| `BUFFER_CAPACITY` | `50000` | Hard cap for backpressure |
| `UPSERT_BATCH_SIZE` | `500` | Max rows per INSERT statement |
| `FLUSH_CHANNEL_CAPACITY` | `2` | Channel capacity between tasks |
| `METRICS_PORT` | `9103` | Prometheus metrics HTTP port |
