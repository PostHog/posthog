# Contract sketch for option A (throwaway)

## Worker: lanes on the rate-limited worker

```ts
type CyclotronV2Lane = {
  /** Highest priority value this lane dequeues; `0` is the transactional class. */
  maxPriority: number
  batchMaxSize: number
  pollDelayMs: number
}

// CyclotronV2WorkerConfig gains:
//   fastLane?: CyclotronV2Lane   // absent = one loop, the current behavior (kill switch)

class CyclotronV2RateLimitedWorker extends CyclotronV2Worker {
  private bulkBatchInFlight = false

  protected override async runConsumerLoop(processBatch: ProcessBatch): Promise<void> {
    await Promise.all([
      this.runBulkLoop(processBatch),
      this.fastLane ? this.runFastLane(processBatch, this.fastLane) : undefined,
    ])
  }

  private async runFastLane(processBatch: ProcessBatch, lane: CyclotronV2Lane): Promise<void> {
    while (this.isConsuming) {
      if (!this.bulkBatchInFlight) {
        await sleep(lane.pollDelayMs) // the bulk loop serves priority 0 first when it is idle
        continue
      }
      const visibleRows = await this.countWork(lane.batchMaxSize, lane.maxPriority)
      if (visibleRows === 0) {
        await sleep(lane.pollDelayMs)
        continue
      }
      const decision = await this.getBatchLimit(visibleRows)
      if (decision?.limit === 0) {
        await sleep(decision.sleepMs ?? lane.pollDelayMs)
        continue
      }
      const rows = await this.fairDequeueJobs(
        Math.min(decision?.limit ?? lane.batchMaxSize, lane.batchMaxSize),
        lane.maxPriority
      )
      await processBatch(rows.map((row) => this.wrapJob(row)))
    }
  }
}
```

## Queries

`countWork` and `fairDequeueJobs` take an optional `maxPriority` and add `AND priority <= $n`.
`idx_cyclotron_jobs_email_priority_fair_dequeue` leads on `priority`, so the fast query is an index range scan.

## Invariants

- One row goes to one loop: both loops dequeue with `FOR UPDATE SKIP LOCKED`.
- Every dequeue still passes `getBatchLimit` first, so the SES rate stays under the bucket. The fast lane claims from the same bucket through the same hook. A separate token design changes the hook body, not its callers.
- With `fastLane` absent the worker behaves as today.

## Error modes

- A stuck event loop stops both loops in that pod. Other pods keep serving priority 0 first. The janitor returns the stuck pod's running rows after the stall timeout.
- `isHealthy` must track each loop's last poll, or a live fast lane hides a stuck bulk loop.
- The worker pool has 10 connections. Background acks and reschedules of a large bulk batch can make the fast dequeue wait for a connection. Give the fast lane its own small pool, or cap background writes.

## Performance

- Zero extra queries while the pod is idle: the fast lane polls only while a bulk batch is in flight.
- While a batch is in flight: one `countWork` per fast poll delay per pod, through the cyclotron pooler.
- The fast batch shares the event loop with the bulk batch. When event loop use is high, fast rows still run slower. That part needs option B or C.
