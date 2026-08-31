# common-kafka-consumer

Kafka consumption core for stateful services: poll, demux to groups, budget-gated admission, contiguous-frontier commits, bounded drain on revoke, per-partition stall watchdog, and commit verification.

The design is the domain side of the driver-model doc in `rust/ingestion-consumer/docs/driver-model.md` (§3.1-§3.7). That doc's §8 is the vocabulary authority for names in this crate.

## Modules

- `config`: `ConsumerConfigBuilder`, the rdkafka `ClientConfig` builder with PostHog consumer defaults.
- `types`: `Partition`, `Offset`, `AssignmentEpoch`, `Advance`, `DrainHarvest`.
- `charge`: `Charge` (events + bytes, one value, two axes) and `Budget`, the `B` gate: charged at poll, refunded at commit or at a drain's end.
- `ledger`: `OffsetLedger`, a dense ring per partition; completion in any order, only the frontier — the highest contiguous completed offset — is ordered.
- `accumulator`: `Group` (one routing key's messages from one poll; null key owes no order), `Accumulator`, and the demux.
- `partition`: `PartitionDriver`, one partition's ledger plus its stall deadline.
- `manager`: `PartitionManager`, assignment lifecycle over the drivers; stragglers die by epoch.
- `commit`: `CommitManager`, the commit policy whole — batched interval issues, immediate final commit on a drain's end.

The invariants (doc §4): only a ledger's frontier is ever committed; an offset goes done only when a completion names it; `B` = polled minus committed, exactly (`tests/exactness.rs` pins this over random schedules); a revoked partition's final commit issues before it is handed back.

Still to come (plan stages 2+): the consumer loop itself (event pump, rdkafka context, pause/resume poll gate, bounded drain wiring, commit monitor), stats export, and the commit sentinel.
