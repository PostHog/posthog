import { ScopedCache } from '@/lib/cache/ScopedCache'

export interface RedisLike {
    get(key: string): Promise<string | null>
    set(key: string, value: string, ...args: (string | number)[]): Promise<string | null>
    del(...keys: string[]): Promise<number>
    scan(cursor: string | number, ...args: (string | number)[]): Promise<[cursor: string, keys: string[]]>
}

const DEFAULT_TTL_SECONDS = 24 * 60 * 60 // 24 hours

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
        try {
            return JSON.parse(raw)
        } catch {
            return raw as T[K]
        }
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        const serialized = typeof value === 'string' ? value : JSON.stringify(value)
        await this.redis.set(scopedKey, serialized, 'EX', this.ttl)
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.del(scopedKey)
    }

    async clear(): Promise<void> {
        const pattern = `mcp:user:${this.scope}:*`
        let cursor = '0'
        do {
            const [nextCursor, keys] = await this.redis.scan(cursor, 'MATCH', pattern, 'COUNT', 100)
            cursor = nextCursor
            if (keys.length > 0) {
                await this.redis.del(...keys)
            }
        } while (cursor !== '0')
    }
}
