// Per-pod concurrency guard for SSE stream connections.
//
// Every stream holds a dedicated blocking-read Redis connection for its whole
// lifetime, so unbounded concurrent streams translate directly into Redis
// connection exhaustion (maxclients) — and a single valid stream-read token is
// enough to open arbitrarily many connections. Two caps bound the blast
// radius: a pod-wide total, and a per-run fanout so one token cannot consume
// the pod's whole budget. Rejected connections receive a 503 and come back
// through the client's normal reconnect backoff.

export type StreamRejectionReason = 'pod_capacity' | 'run_capacity'

export class StreamCapacity {
    private total = 0
    private readonly byRun = new Map<string, number>()

    constructor(
        private readonly maxTotal: number,
        private readonly maxPerRun: number
    ) {}

    /** Reserve a slot for runId. Returns the rejection reason, or null when acquired. */
    tryAcquire(runId: string): StreamRejectionReason | null {
        if (this.total >= this.maxTotal) {
            return 'pod_capacity'
        }
        const runCount = this.byRun.get(runId) ?? 0
        if (runCount >= this.maxPerRun) {
            return 'run_capacity'
        }
        this.total += 1
        this.byRun.set(runId, runCount + 1)
        return null
    }

    /** Release a previously acquired slot. Must be called exactly once per successful tryAcquire. */
    release(runId: string): void {
        this.total = Math.max(0, this.total - 1)
        const runCount = this.byRun.get(runId) ?? 0
        if (runCount <= 1) {
            this.byRun.delete(runId)
        } else {
            this.byRun.set(runId, runCount - 1)
        }
    }

    get openTotal(): number {
        return this.total
    }
}
