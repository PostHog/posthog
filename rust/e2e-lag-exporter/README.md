# e2e-lag-exporter

A Rust service that monitors Kafka consumer group lag and exports metrics for Prometheus.

## Features

- Tracks the number of messages behind for a consumer group (message count lag)
- Tracks the time lag based on message timestamps (how old are the latest messages processed)
- Exports metrics in Prometheus format

## Configuration

Configuration is done via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `KAFKA_HOSTS` | Comma-separated list of Kafka brokers | `kafka:9092` |
| `KAFKA_CONSUMERGROUP` | Consumer group to monitor | _required_ |
| `CHECK_INTERVAL_MS` | How often to check lag (milliseconds) | `20000` |
| `METRICS_PORT` | Port to expose Prometheus metrics | `9090` |
| `LOG_LEVEL` | Logging level | `info` |

## Metrics

The service exposes the following metrics:

- `consumer_lag` - Number of messages behind for the consumer group (per topic/partition)
- `consumer_last_message_timestamp` - Timestamp of the last message received on the group (per topic/partition)

## Usage

```bash
# Build the service
cargo build --release

# Run with default settings
./target/release/e2e-lag-exporter

# Run with custom settings
KAFKA_HOSTS=localhost:9092 KAFKA_CONSUMERGROUP=my-group METRICS_PORT=9090 ./target/release/e2e-lag-exporter
```
