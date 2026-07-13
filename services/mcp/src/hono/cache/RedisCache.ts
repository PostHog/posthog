import { ScopedCache } from '@/lib/cache/ScopedCache'

import { redisOperationsTotal } from '../metrics'

export interface RedisLike {
    get(key: string): Promise<string | null>
    set(key: string, value: string, ...args: (string | number)[]): Promise<string | null>
    del(...keys: string[]): Promise<number>
    unlink?(...keys: string[]): Promise<number>
    getdel?(key: string): Promise<string | null>
    scan(cursor: string | number, ...args: (string | number)[]): Promise<[cursor: string, keys: string[]]>
    incr(key: string): Promise<number>
    expire(key: string, seconds: number): Promise<number>
    ttl(key: string): Promise<number>
}

const DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days
const CLEAR_MAX_ITERATIONS = 50
const CLEAR_SCAN_COUNT = 100

export type CachePrefix = 'token' | 'session' | 'user'

export class RedisCache<T extends Record<string, any>> extends ScopedCache<T> {
    private redis: RedisLike
    private ttl: number
    private prefix: CachePrefix

    constructor(
        scope: string,
        redis: RedisLike,
        prefix: CachePrefix = 'token',
        ttlSeconds: number = DEFAULT_TTL_SECONDS
    ) {
        super(scope)
        this.redis = redis
        this.prefix = prefix
        this.ttl = ttlSeconds
    }

    private getScopedKey(key: string): string {
        return `mcp:${this.prefix}:${this.scope}:${key}`
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        const scopedKey = this.getScopedKey(key as string)
        try {
            const raw = await this.redis.get(scopedKey)
            if (raw === null) {
                redisOperationsTotal.inc({ operation: 'get', status: 'success' })
                return undefined
            }
            const result = JSON.parse(raw) as T[K]
            redisOperationsTotal.inc({ operation: 'get', status: 'success' })
            return result
        } catch (error) {
            redisOperationsTotal.inc({ operation: 'get', status: 'error' })
            throw error
        }
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        try {
            await this.redis.set(scopedKey, JSON.stringify(value), 'EX', this.ttl)
            redisOperationsTotal.inc({ operation: 'set', status: 'success' })
        } catch (error) {
            redisOperationsTotal.inc({ operation: 'set', status: 'error' })
            throw error
        }
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.del(scopedKey)
    }

    async clear(): Promise<void> {
        const pattern = `mcp:${this.prefix}:${this.scope}:*`
        let cursor = '0'
        const unlink = this.redis.unlink?.bind(this.redis) ?? this.redis.del.bind(this.redis)
        for (let i = 0; i < CLEAR_MAX_ITERATIONS; i += 1) {
            const [nextCursor, keys] = await this.redis.scan(cursor, 'MATCH', pattern, 'COUNT', CLEAR_SCAN_COUNT)
            cursor = nextCursor
            if (keys.length > 0) {
                try {
                    await unlink(...keys)
                } catch (err) {
                    console.error('[RedisCache] clear() failed mid-iteration:', err)
                }
            }
            if (cursor === '0') {
                return
            }
        }
        console.warn(`[RedisCache] clear() hit iteration cap (${CLEAR_MAX_ITERATIONS}); remaining keys will TTL-evict`)
    }
}
