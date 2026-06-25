# Cymbal notifications review notes

## Race conditions and regressions

### DB commit succeeds but notification publish fails

Created and reopened flows commit the issue state before publishing the ingestion notification.
If the Kafka publish fails after the DB transition, retrying the original event may no longer recreate the lifecycle transition:

- Created retry sees an existing active issue, so no `IssueCreated` notification is published.
- Reopened retry sees an already active issue, so no `IssueReopened` notification is published.

This can permanently lose notification-side effects.
The strongest fix is a transactional outbox written in the same Postgres transaction as the issue transition, with a worker publishing outbox rows to Kafka.
A smaller mitigation is to persist a pending side-effect marker with the transition and make notification publishing recoverable.

### Signal emission remains best-effort and can duplicate

Signal emission is intentionally left best-effort and outside the retry-critical path.
If notification handling is retried after signal emission, a signal can be emitted more than once.

### Notifications load current issue state rather than transition-time state

The notifications handler loads issue name, status, description, and created_at from Postgres when the notification is handled.
If the issue is renamed, resolved, suppressed, or deleted before handling, side effects may describe the later state rather than the original transition.

Consider including the issue snapshot needed for side effects in the notification payload.
That would also remove the notification-side DB read.

## Fixed in current changes

### Notification payloads are keyed

Processing now publishes ingestion notifications with `send_keyed_iter_to_kafka` and a stable `"{team_id}:{issue_id}"` key.
This preserves per-issue ordering across Kafka partitions.

### Notification commits are batched

The notifications consumer keeps `enable.auto.commit=false`, fetches notifications in small batches, stores offsets after successful handling, and explicitly commits in batches by count or time.
It also flushes pending offsets on shutdown and before crashing on a handler error.
This reduces per-message fetch and commit overhead while preserving explicit offset control.
The tradeoff remains that a crash after side effects but before the batch commit replays the uncommitted tail, so idempotency is still important.

### Signals run after required side effects

Signal emission is treated as best-effort.
The notifications handler now runs required fallible work first, then emits signals.
Signal failures only affect signal metrics/logs and do not block offset commits.

### Retryable notification side effects have stable ids

Each ingestion notification now carries a stable `notification_id`.
Spike event persistence uses that id as the row id with `ON CONFLICT DO NOTHING`, so notification retries do not create duplicate `posthog_errortrackingspikeevent` rows.
Internal events reuse the same id as the event UUID, giving downstream ingestion a stable dedupe key across retries.

## Optimizations

### Batch spike notification publishes

Spike notification publishing currently loops and awaits one Kafka publish per acquired spike lock.
Build a list of notifications and send them with one Kafka call, then release cooldown locks for failed publish results.

### Avoid notification-side DB reads

Carry the issue snapshot fields needed by side effects in the notification payload:

- issue name
- issue description
- issue status
- issue created_at

This removes one Postgres read per notification and avoids stale/current-state races.

### Reorder side effects

Run durable or retry-critical work before best-effort work.
For example, persist/produce required side effects first, then emit analytics/signals if they are best-effort.
This reduces duplicate best-effort side effects when a later required operation fails.

## Priority

Highest priority before merge:

1. Close or explicitly accept the DB-commit/Kafka-publish gap for created and reopened lifecycle notifications.
2. Explicitly accept best-effort signal duplication, or add signal-side idempotency in a separate change.

After that, consider batching spike notification publishes for throughput.
