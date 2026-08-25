// Per-key, per-deployment usage counters in Postgres: who actually reads this credential,
// and have they picked up the new value. Writes are batched and flushed on a timer, so an
// upsert never lands on the hot path and a crash loses at most one interval of counts.
//
// No credential value reaches this module — key names, deployment names, counts, timestamps.

import type { Pool } from 'pg'

import { logger } from '../lib/logging'

interface Pending {
    key: string
    deployment: string
    reads: number
    lastSeen: number
}

// Composite lookup key. Never parsed back apart: the fields travel on the Pending entry.
function pendingId(key: string, deployment: string): string {
    return `${key}|${deployment}`
}

/** Truncate to the hour, so a rolling window is a sum over a small number of rows. */
function hourBucket(at: number): Date {
    const d = new Date(at)
    d.setUTCMinutes(0, 0, 0)
    return d
}

export interface UsageRecorderOptions {
    pool?: Pool | undefined
    now?: () => number
}

export class UsageRecorder {
    private readonly pool: Pool | undefined
    private readonly now: () => number
    private pending = new Map<string, Pending>()

    constructor(opts: UsageRecorderOptions) {
        this.pool = opts.pool
        this.now = opts.now ?? Date.now
    }

    /** Accumulate a batch of reads. Never touches the database on the request path. */
    record(deployment: string, servedKeys: readonly string[]): void {
        if (servedKeys.length === 0) {
            return
        }
        const at = this.now()
        for (const key of servedKeys) {
            const entry = this.pending.get(pendingId(key, deployment))
            if (entry) {
                entry.reads += 1
                entry.lastSeen = Math.max(entry.lastSeen, at)
            } else {
                this.pending.set(pendingId(key, deployment), { key, deployment, reads: 1, lastSeen: at })
            }
        }
    }

    /** Write what has accumulated. Safe to call when nothing is pending. */
    async flush(): Promise<void> {
        if (!this.pool || this.pending.size === 0) {
            return
        }
        // Swap first: a failed write must not block the next request from accumulating,
        // and re-queueing on failure would let a broken database grow this map without
        // bound. Losing a flush costs counts, not correctness of `last_seen` ordering.
        const batch = this.pending
        this.pending = new Map()

        const keys: string[] = []
        const deployments: string[] = []
        const buckets: Date[] = []
        const reads: number[] = []
        const lastSeen: Date[] = []
        for (const entry of batch.values()) {
            keys.push(entry.key)
            deployments.push(entry.deployment)
            buckets.push(hourBucket(entry.lastSeen))
            reads.push(entry.reads)
            lastSeen.push(new Date(entry.lastSeen))
        }

        try {
            await this.pool.query(
                `INSERT INTO integration_secret_usage (secret_key, deployment, bucket, reads, last_seen)
                 SELECT * FROM unnest($1::text[], $2::text[], $3::timestamptz[], $4::bigint[], $5::timestamptz[])
                 ON CONFLICT (secret_key, deployment, bucket) DO UPDATE
                 SET reads = integration_secret_usage.reads + EXCLUDED.reads,
                     last_seen = GREATEST(integration_secret_usage.last_seen, EXCLUDED.last_seen)`,
                [keys, deployments, buckets, reads, lastSeen]
            )
            await this.pool.query(
                `INSERT INTO integration_secret_last_seen (secret_key, deployment, last_seen)
                 SELECT * FROM unnest($1::text[], $2::text[], $3::timestamptz[])
                 ON CONFLICT (secret_key, deployment) DO UPDATE
                 SET last_seen = GREATEST(integration_secret_last_seen.last_seen, EXCLUDED.last_seen)`,
                [keys, deployments, lastSeen]
            )
        } catch (err) {
            logger.warn('usage:flush_failed', {
                entries: batch.size,
                error: err instanceof Error ? err.message : String(err),
            })
        }
    }

    /**
     * Drop buckets past the retention window. Never touches integration_secret_last_seen: a
     * dormant deployment holds the retirement verdict back however long it has been quiet.
     *
     * A deployment whose signing key is later revoked keeps its last_seen row too — this
     * table records what was read, not who is still allowed to read it. Judging a row against
     * "is this deployment still active" is the retirement verdict's job (the follow-up UI PR),
     * which can filter by currently active deployments; guessing at revocation here by pruning
     * would reintroduce the exact failure mode last_seen exists to prevent, a rotation looking
     * safe to complete because a caller went quiet.
     */
    async prune(retentionDays: number): Promise<void> {
        if (!this.pool) {
            return
        }
        try {
            await this.pool.query(
                `DELETE FROM integration_secret_usage WHERE bucket < now() - make_interval(days => $1)`,
                [retentionDays]
            )
        } catch (err) {
            logger.warn('usage:prune_failed', { error: err instanceof Error ? err.message : String(err) })
        }
    }
}
