# common-kafka-consumer

Kafka consumption core for stateful services: poll, demux to groups, budget-gated admission, contiguous-frontier commits, bounded drain on revoke, per-partition stall watchdog, and commit verification.

The design is the domain side of the driver-model doc in `rust/ingestion-consumer/docs/driver-model.md` (§3.1-§3.7). That doc's §8 is the vocabulary authority for names in this crate.

## The seam

The loop owns the left side. The application (the transport side) owns the right and talks only through the two channels.

```text
                 Feed { Batch(Accumulator) | Revoked { partition, epoch } }
consumer loop ─────────────────────────────────────────────────────────►  transport side
              ◄─────────────────────────────────────────────────────────
                 Completion { Completed(Vec<GroupCompletion>) | Drained { partition, epoch } }
```

Rules the transport side must keep:

- A `Group` comes back as one `GroupCompletion` (`Group::completion`), slim: partition, epoch, done offsets, no messages. Only when its work is done; a partial acceptance narrows the offsets to the accepted prefix. Failures never cross the seam: keep the group and retry; its offsets stay pending.
- One assignment epoch per process: `ConsumerLoop::epoch_counter` is the counter the transport stamps on requests, so worker-side sentinels rebaseline on the same rebalances the groups see.
- `Revoked` is in-band: drop the partition's queued groups (never sent, the next owner re-reads them), let in-flight work settle, then send `Drained` with the same epoch behind the last completion. Groups for that partition that arrive after the marker are dropped too.
- Shutdown is a `Revoked` for every partition; nothing else changes.

## Modules

- `config`: `ConsumerConfigBuilder`, the rdkafka `ClientConfig` builder with PostHog consumer defaults.
- `consumer_loop`: `ConsumerLoop`, the event pump: a biased select over shutdown, the housekeeping tick, rebalance events, completions, and the poll. `ConsumerLoopConfig` carries every knob with defaults.
- `context`: the rdkafka `ConsumerContext`: `incremental_assign` in the callback, revokes forwarded to the loop, the hand-back deferred to the drain's end; `closing` makes the close-time revoke answer inline.
- `types`: `Partition`, `Offset`, `AssignmentEpoch`, `Advance`, `DrainHarvest`, `RawMessage`.
- `charge`: `Charge` (events + bytes, one value, two axes) and `Budget`, the `B` gate with two watermarks: closes at `cap`, reopens at `low`.
- `ledger`: `OffsetLedger`, a dense ring per partition; completion in any order, only the frontier — the highest contiguous completed offset — is ordered.
- `accumulator`: `Group` (one routing key's messages from one poll; null key owes no order), `Accumulator`, and the demux.
- `partition`: `PartitionDriver`, one partition's ledger plus its stall deadline.
- `manager`: `PartitionManager`, assignment lifecycle over the drivers; stragglers die by epoch.
- `commit`: `CommitManager`, the commit policy whole — batched interval issues, immediate final commit on a drain's end, `abandon` for a lost assignment.
- `sentinel`: `CommitSentinel`, the cheap assert that issues only move forward, and the broker-side confirmation the commit monitor feeds.
- `stats`: librdkafka statistics export, unlabeled series.
- `events`: `Observer`, the loop-side event points (`alive` for liveness, assign/revoke/drain/commit/stall/gate).
- `metrics`: every metric name, pinned by a fixture test; every labeled series carries `group`.

## Invariants (doc §4)

Only a ledger's frontier is ever committed; an offset goes done only when a completion names it; `B` = polled minus committed, exactly (`tests/exactness.rs` pins this over random schedules); a revoked partition's final commit issues before it is handed back (`tests/mock_cluster.rs`).

## Facts about rdkafka the loop is built around

- The rebalance callback runs inside `poll`, on the task that awaits `recv()`: the loop's own. It never waits there; the hand-back (`incremental_unassign`) comes from the loop after the drain, which librdkafka allows outside the callback.
- While a revoke waits for that call, librdkafka pauses every assigned partition. The drain window is a pod-wide fetch pause; keep it short.
- Dropping the consumer revokes the whole assignment through the same callback and polls until closed; the `closing` flag answers that one inline, or the drop spins forever.
- `pause` purges the fetch queue and `resume` refetches it, hence the gate's two watermarks.
- The poll arm is never disabled: a paused consumer still serves callbacks and keeps `max.poll.interval.ms` alive; an unpolled one does neither.
