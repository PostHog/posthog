import { ScopedCache } from '@/lib/cache/ScopedCache'

export interface RedisLike {
    get(key: string): Promise<string | null>
    set(key: string, value: string, ...args: (string | number)[]): Promise<string | null>
    del(...keys: string[]): Promise<number>
    unlink?(...keys: string[]): Promise<number>
    scan(cursor: string | number, ...args: (string | number)[]): Promise<[cursor: string, keys: string[]]>
}

const DEFAULT_TTL_SECONDS = 7 * 24 * 60 * 60 // 7 days
// Cap on clear()'s SCAN/UNLINK pass. A user with more than this many cache
// entries either deserves an explicit GC pass or is misbehaving — either way
// we don't want a single request to stall on an unbounded loop.
const CLEAR_MAX_ITERATIONS = 50
const CLEAR_SCAN_COUNT = 100

export class RedisCache<T extends Record<string, any>> extends ScopedCache<T> {
    private redis: RedisLike
    private ttl: number

    constructor(scope: string, redis: RedisLike, ttlSeconds: number = DEFAULT_TTL_SECONDS) {
        super(scope)
        this.redis = redis
        this.ttl = ttlSeconds
    }

    private getScopedKey(key: string): string {
        return `mcp:user:${this.scope}:${key}`
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        const scopedKey = this.getScopedKey(key as string)
        const raw = await this.redis.get(scopedKey)
        if (raw === null) {
            return undefined
        }
        return JSON.parse(raw) as T[K]
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.set(scopedKey, JSON.stringify(value), 'EX', this.ttl)
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.del(scopedKey)
    }

    async clear(): Promise<void> {
        const pattern = `mcp:user:${this.scope}:*`
        let cursor = '0'
        // UNLINK lets Redis free memory in a background thread; falls back to DEL
        // for clients that don't expose it. Iteration cap is a guard against
        // pathological scans on outlier accounts — a partial clear is acceptable
        // (the remaining entries will TTL-evict).
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
