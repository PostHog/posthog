# common-kafka-consumer

Kafka consumption primitives shared by stateful services.

## Modules

- `config`: `ConsumerConfigBuilder`, the rdkafka `ClientConfig` builder with PostHog consumer defaults.
- `types`: `Offset` and `Partition`.
- `accumulator`: `Group`, one routing key's messages from one poll on one partition, and `Accumulator`, the demux that builds a poll's groups.
- `charge`: `Charge`, a message's cost (events and bytes) against consumer admission budgets.
- `partition_offset_ledger`: `PartitionOffsetLedger`, offset accounting scoped to one partition assignment: completion in any order, an observable contiguous frontier, and explicit consumption at commit points.
- `topic_offset_ledger`: `TopicOffsetLedger`, one partition ledger per assigned topic-partition, keyed by generation so work from a previous assignment cannot land on the current one.

## Metrics

`TopicOffsetLedger` publishes these itself, so every consumer built on the crate reports the same series.

| Metric | Labels | Meaning |
| --- | --- | --- |
| `kafka_consumer_ledger_uncommitted_offsets` (gauge) | `topic`, `partition` | Offsets the partition's window holds. |
| `kafka_consumer_ledger_uncommitted_events` (gauge) | `topic`, `partition` | Events those offsets carry. |
| `kafka_consumer_ledger_uncommitted_bytes` (gauge) | `topic`, `partition` | Bytes those offsets carry (payload plus key plus headers). |
| `kafka_consumer_ledger_stale_slices_total` (counter) | `stage` | Charges and settlements dropped because their partition was reassigned while they were in flight; a few around a rebalance are expected. |
| `kafka_consumer_ledger_errors_total` (counter) | `stage`, `kind` | Contract violations in the accounting; must stay 0. A violation resets that partition's ledger and the consumer keeps running. |
