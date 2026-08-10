// Per-key, per-deployment usage counters, held in Postgres.
//
// This answers "who actually reads this credential, and have they picked up the new value"
// — the two questions a rotation turns on. Prometheus carries the same signal, but
// per-replica and per-region, and the secrets UI runs in the internal cluster. Rolling it
// up here means the UI reads one S3 object instead of querying metrics across clusters.
//
// Writes are batched in memory and flushed on a timer rather than issued per read. Callers
// no longer cache, so every credential read reaches this service; an upsert per read would
// put a write on the hot path for no benefit. A crash loses at most one flush interval of
// counts, which is acceptable for usage totals and does not affect `last_seen` materially.
//
// No credential value ever reaches this module. It stores key NAMES, deployment names,
// counts and timestamps.

import type { Pool } from 'pg'

import { logger } from '../lib/logging.js'

interface Pending {
    reads: number
    lastSeen: number
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
            const field = `${key}|${deployment}`
            const entry = this.pending.get(field)
            if (entry) {
                entry.reads += 1
                entry.lastSeen = Math.max(entry.lastSeen, at)
            } else {
                this.pending.set(field, { reads: 1, lastSeen: at })
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
        for (const [field, entry] of batch) {
            const sep = field.lastIndexOf('|')
            keys.push(field.slice(0, sep))
            deployments.push(field.slice(sep + 1))
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
     * Reads inside the window, and last-seen across all time.
     *
     * The two come from different tables on purpose. Window-filtering last-seen would drop
     * a deployment that reads a key less often than the window out of the retirement
     * verdict entirely — see the note on integration_secret_last_seen.
     */
    async summarize(hours: number): Promise<{
        reads: Map<string, number>
        lastSeen: Map<string, number>
    }> {
        const reads = new Map<string, number>()
        const lastSeen = new Map<string, number>()
        if (!this.pool) {
            return { reads, lastSeen }
        }

        const counted = await this.pool.query<{ secret_key: string; deployment: string; reads: string }>(
            `SELECT secret_key, deployment, SUM(reads) AS reads
             FROM integration_secret_usage
             WHERE bucket >= now() - make_interval(hours => $1)
             GROUP BY secret_key, deployment`,
            [hours]
        )
        for (const row of counted.rows) {
            reads.set(`${row.secret_key}|${row.deployment}`, Number(row.reads))
        }

        const seen = await this.pool.query<{ secret_key: string; deployment: string; last_seen: Date }>(
            `SELECT secret_key, deployment, last_seen FROM integration_secret_last_seen`
        )
        for (const row of seen.rows) {
            lastSeen.set(`${row.secret_key}|${row.deployment}`, row.last_seen.getTime())
        }

        return { reads, lastSeen }
    }

    /**
     * Drop buckets past the retention window, so the counts table stays small.
     *
     * Deliberately does not touch integration_secret_last_seen: a dormant deployment has to
     * keep holding the retirement verdict back however long it has been quiet.
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
