import crypto from 'node:crypto'

import { gunzipSync, gzipSync, strFromU8, strToU8 } from 'fflate'

import type { EvaluatedFlags, FlagGroups } from '@/lib/posthog/flags'

import { redisOperationsTotal } from '../metrics'
import type { RedisLike } from './RedisCache'

// Sized to warm a returning user's connection so the first request of a new
// session skips the flags API call. Across 90 days of production traffic the
// gap between a user's sessions is p50 ~9h / p75 ~28h / p90 ~4.7d, so a 7-day
// window covers ~93.5% of returning sessions (vs 70% at 24h, 80% at 48h) with
// diminishing returns beyond. Tool-gating flags only decide which MCP tools are
// visible and change at the cadence of rollout edits, so this matches the 7-day
// TTL the sibling token cache (distinctId/projectId/orgId) already uses for the
// same connection-speedup purpose — see RedisCache DEFAULT_TTL_SECONDS.
export const FLAG_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

const FLAG_CACHE_PREFIX = 'mcp:flags'

// Cache keys need a fast, one-way, collision-resistant digest — not the slow
// password-grade KDF in `hash()` (PBKDF2, 100k iterations), which would block
// the event loop on every get/set and negate the round-trip this cache saves.
function digest(data: string): string {
    return crypto.createHash('sha256').update(data).digest('hex')
}

/**
 * Per-user Redis cache for evaluated feature flags, gzip-compressed before write.
 *
 * The cache key is scoped to the user's `distinctId` plus a signature of the
 * requested flag keys and the analytics groups (org/project), since group-based
 * flags evaluate differently per context and the stored map only holds values
 * for the keys evaluated at write time.
 */
export class FeatureFlagCache {
    constructor(
        private readonly redis: RedisLike,
        private readonly ttlSeconds: number = FLAG_CACHE_TTL_SECONDS
    ) {}

    /** Stable cache key independent of flag-key / group ordering. */
    buildKey(distinctId: string, flagKeys: string[], groups?: FlagGroups): string {
        const sortedKeys = [...flagKeys].sort()
        const sortedGroups = Object.entries(groups ?? {}).sort(([a], [b]) => a.localeCompare(b))
        const signature = digest(JSON.stringify({ keys: sortedKeys, groups: sortedGroups }))
        return `${FLAG_CACHE_PREFIX}:${digest(distinctId)}:${signature}`
    }

    async get(distinctId: string, flagKeys: string[], groups?: FlagGroups): Promise<EvaluatedFlags | undefined> {
        const key = this.buildKey(distinctId, flagKeys, groups)
        try {
            const raw = await this.redis.get(key)
            if (raw === null) {
                redisOperationsTotal.inc({ operation: 'get', status: 'success' })
                return undefined
            }
            const compressed = Buffer.from(raw, 'base64')
            const json = strFromU8(
                gunzipSync(new Uint8Array(compressed.buffer, compressed.byteOffset, compressed.byteLength))
            )
            redisOperationsTotal.inc({ operation: 'get', status: 'success' })
            return JSON.parse(json) as EvaluatedFlags
        } catch (error) {
            // Treat any read/decompress failure as a miss so callers fall back to live evaluation.
            redisOperationsTotal.inc({ operation: 'get', status: 'error' })
            console.error('[FeatureFlagCache] get() failed:', error)
            return undefined
        }
    }

    async set(distinctId: string, flagKeys: string[], flags: EvaluatedFlags, groups?: FlagGroups): Promise<void> {
        const key = this.buildKey(distinctId, flagKeys, groups)
        try {
            const compressed = gzipSync(strToU8(JSON.stringify(flags)))
            const b64 = Buffer.from(compressed.buffer, compressed.byteOffset, compressed.byteLength).toString('base64')
            await this.redis.set(key, b64, 'EX', this.ttlSeconds)
            redisOperationsTotal.inc({ operation: 'set', status: 'success' })
        } catch (error) {
            // A cache write failure must never break flag resolution — log and move on.
            redisOperationsTotal.inc({ operation: 'set', status: 'error' })
            console.error('[FeatureFlagCache] set() failed:', error)
        }
    }
}
