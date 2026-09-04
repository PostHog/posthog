# common-kafka-consumer

Kafka consumption primitives shared by stateful services.

## Modules

- `config`: `ConsumerConfigBuilder`, the rdkafka `ClientConfig` builder with PostHog consumer defaults.
- `types`: `Offset` and `Partition`.
- `accumulator`: `Group`, one routing key's messages from one poll on one partition, and `Accumulator`, the demux that builds a poll's groups.
- `charge`: `Charge`, a message's cost (events and bytes) against consumer admission budgets.
- `ledger`: `OffsetLedger`, offset accounting scoped to one partition assignment: completion in any order, an observable contiguous frontier, and explicit consumption at commit points.
