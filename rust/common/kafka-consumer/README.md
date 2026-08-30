# common-kafka-consumer

Kafka consumption core for stateful services: poll, demux to groups, budget-gated admission, contiguous-frontier commits, bounded drain on revoke, per-partition stall watchdog, and commit verification.

The design is the domain side of the driver-model doc in `rust/ingestion-consumer/docs/driver-model.md` (§3.1-§3.7). That doc's §8 is the vocabulary authority for names in this crate.

## Modules

- `config`: `ConsumerConfigBuilder`, the rdkafka `ClientConfig` builder with PostHog consumer defaults.
