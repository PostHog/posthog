// Per-key, per-caller usage counters, kept in Redis so they survive a replica restart
// and aggregate across the whole deployment.
//
// This is what answers "who actually reads this credential, and is the old value still
// needed" — the two questions a rotation turns on. Prometheus already carries the same
// signal, but per-replica and per-region, and the secrets UI runs in the internal
// cluster; rolling it up here means the UI reads one S3 object instead of querying
// metrics across clusters.
//
// Counters are bucketed by hour so a rolling 24h window is a sum of 24 hashes rather
// than a scan. Stored in plaintext deliberately: these are caller names, key NAMES,
// counts and timestamps — the same sensitivity class as the consumption map the
// secrets UI already publishes. No credential value ever reaches this module.

import type { Redis } from 'ioredis'

import { logger } from '../lib/logging.js'

/** Hourly buckets kept around long enough to serve a 7-day view with room to spare. */
const BUCKET_TTL_SECONDS = 9 * 24 * 60 * 60

export const READS_SUFFIX = 'reads'
export const PREVIOUS_SUFFIX = 'prev'

export function hourBucket(at: number): string {
    return new Date(at).toISOString().slice(0, 13).replace(/[-T]/g, '')
}

export function bucketKey(env: string, bucket: string): string {
    return `integration-service:v1:${env}:usage:${bucket}`
}

export function lastSeenKey(env: string): string {
    return `integration-service:v1:${env}:usage:lastseen`
}

/** Hash field name. `|` is safe: neither a credential key name nor a caller name contains one. */
export function usageField(key: string, caller: string, suffix: string): string {
    return `${key}|${caller}|${suffix}`
}

export interface UsageRecorderOptions {
    redis?: Redis | undefined
    env: string
    now?: () => number
}

export class UsageRecorder {
    private readonly redis: Redis | undefined
    private readonly env: string
    private readonly now: () => number

    constructor(opts: UsageRecorderOptions) {
        this.redis = opts.redis
        this.env = opts.env
        this.now = opts.now ?? Date.now
    }

    /**
     * Record a batch of reads for one caller. Fire-and-forget from the request path:
     * usage accounting must never be the reason a credential read fails.
     */
    record(caller: string, servedKeys: readonly string[], previousUsedKeys: readonly string[]): void {
        if (!this.redis || (servedKeys.length === 0 && previousUsedKeys.length === 0)) {
            return
        }
        const at = this.now()
        const bucket = bucketKey(this.env, hourBucket(at))
        const lastSeen = lastSeenKey(this.env)
        const pipeline = this.redis.pipeline()

        for (const key of servedKeys) {
            pipeline.hincrby(bucket, usageField(key, caller, READS_SUFFIX), 1)
            pipeline.hset(lastSeen, usageField(key, caller, READS_SUFFIX), String(at))
        }
        for (const key of previousUsedKeys) {
            pipeline.hincrby(bucket, usageField(key, caller, PREVIOUS_SUFFIX), 1)
        }
        pipeline.expire(bucket, BUCKET_TTL_SECONDS)

        pipeline.exec().catch((err: unknown) => {
            logger.warn('usage:record_failed', { error: err instanceof Error ? err.message : String(err) })
        })
    }

    /** Read back the last `hours` buckets, summed per key/caller. */
    async summarize(hours: number): Promise<{
        reads: Map<string, number>
        previousUsed: Map<string, number>
        lastSeen: Map<string, number>
    }> {
        const reads = new Map<string, number>()
        const previousUsed = new Map<string, number>()
        const lastSeen = new Map<string, number>()
        if (!this.redis) {
            return { reads, previousUsed, lastSeen }
        }

        const at = this.now()
        const pipeline = this.redis.pipeline()
        for (let i = 0; i < hours; i++) {
            pipeline.hgetall(bucketKey(this.env, hourBucket(at - i * 60 * 60 * 1000)))
        }
        pipeline.hgetall(lastSeenKey(this.env))
        const results = await pipeline.exec()

        if (!results) {
            return { reads, previousUsed, lastSeen }
        }

        for (let i = 0; i < hours; i++) {
            const entry = results[i]
            const hash = entry?.[1] as Record<string, string> | undefined
            if (!hash) {
                continue
            }
            for (const [field, raw] of Object.entries(hash)) {
                const count = Number.parseInt(raw, 10)
                if (Number.isNaN(count)) {
                    continue
                }
                const target = field.endsWith(`|${PREVIOUS_SUFFIX}`) ? previousUsed : reads
                const stripped = field.slice(0, field.lastIndexOf('|'))
                target.set(stripped, (target.get(stripped) ?? 0) + count)
            }
        }

        const lastSeenHash = results[hours]?.[1] as Record<string, string> | undefined
        if (lastSeenHash) {
            for (const [field, raw] of Object.entries(lastSeenHash)) {
                const at2 = Number.parseInt(raw, 10)
                if (!Number.isNaN(at2)) {
                    lastSeen.set(field.slice(0, field.lastIndexOf('|')), at2)
                }
            }
        }

        return { reads, previousUsed, lastSeen }
    }
}
