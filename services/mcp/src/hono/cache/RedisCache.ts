import { ScopedCache } from '@/lib/cache/ScopedCache'

const DEFAULT_TTL_SECONDS = 86400

export interface RedisLike {
    get(key: string): Promise<string | null>
    set(key: string, value: string, expiryMode: string, time: number): Promise<string | null>
    del(...keys: string[]): Promise<number>
    scan(cursor: string, matchOption: string, pattern: string, countOption: string, count: number): Promise<[cursor: string, keys: string[]]>
}

export class RedisCache<T extends Record<string, any>> extends ScopedCache<T> {
    private redis: RedisLike
    private userHash: string
    private ttl: number

    constructor(scope: string, redis: RedisLike, ttl: number = DEFAULT_TTL_SECONDS) {
        super(scope)
        this.userHash = scope
        this.redis = redis
        this.ttl = ttl
    }

    private getScopedKey(key: string): string {
        return `mcp:user:${this.userHash}:${key}`
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        const scopedKey = this.getScopedKey(key as string)
        const raw = await this.redis.get(scopedKey)
        if (raw === null) {
            return undefined
        }
        try {
            return JSON.parse(raw) as T[K]
        } catch {
            return raw as T[K] & string
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
        const pattern = `mcp:user:${this.userHash}:*`
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
