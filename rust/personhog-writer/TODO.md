# personhog-writer follow-ups

## Per-partition parallel writes

The writer is currently serial: one batch at a time, commit offsets, then
next batch. Under PG latency spikes this backpressures the consumer quickly.

The natural evolution is per-partition writer tasks:

- Use rdkafka rebalance callbacks (`on_assign` / `on_revoke`) to spawn/drain
  a writer task per assigned partition.
- Each partition's batches are processed serially (preserving offset order),
  but different partitions write in parallel.
- Offset commits stay safe because each partition's offsets are managed
  independently.
- Cooperative-sticky assignment minimizes churn during deploys.

No coordinator integration needed — Kafka's consumer group protocol handles
partition assignment. The coordinator would only matter if we wanted writer
and leader co-located on the same partitions.

## Flush channel capacity

Default `flush_channel_capacity` is 8. Tune down if memory is a concern,
or up if PG latency causes frequent backpressure under production load.

## Leader-side validation

Add input validation/sanitization in personhog-leader before producing to
`personhog_updates`:

- Validate UUID format
- Validate properties are well-formed JSON
- Enforce size limits before publishing

This shifts failure detection earlier and keeps the writer's error paths
rare.

## Production cutover

Once validation confirms parity with the Node pipeline:

1. Switch `PG_TARGET_TABLE` from `personhog_person_tmp` to `posthog_person`
2. Drop `personhog_person_tmp` table
3. Remove `personhog_person_tmp` from the table allowlist
