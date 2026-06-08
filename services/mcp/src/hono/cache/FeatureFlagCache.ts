import { gunzipSync, gzipSync, strFromU8, strToU8 } from 'fflate'

import type { EvaluatedFlags, FlagGroups } from '@/lib/posthog/flags'
import { hash } from '@/lib/utils'

import { redisOperationsTotal } from '../metrics'
import type { RedisLike } from './RedisCache'

// Tool-gating flags only decide which MCP tools are visible and change at the
// cadence of rollout edits, while MCP sessions fire many requests over a few
// minutes — so a short window absorbs the in-session burst while keeping flag
// changes propagating quickly.
export const FLAG_CACHE_TTL_SECONDS = 5 * 60

const FLAG_CACHE_PREFIX = 'mcp:flags'

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
        const signature = hash(JSON.stringify({ keys: sortedKeys, groups: sortedGroups }))
        return `${FLAG_CACHE_PREFIX}:${hash(distinctId)}:${signature}`
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
