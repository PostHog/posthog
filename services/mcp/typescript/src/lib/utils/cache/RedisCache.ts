import type { Redis } from 'ioredis'

import { ScopedCache } from '@/lib/utils/cache/ScopedCache'

const DEFAULT_TTL_SECONDS = 300 // 5 minutes

export class RedisCache<T extends Record<string, any>> extends ScopedCache<T> {
    private redis: Redis
    private ttlSeconds: number

    constructor(scope: string, redis: Redis, ttlSeconds: number = DEFAULT_TTL_SECONDS) {
        super(scope)
        this.redis = redis
        this.ttlSeconds = ttlSeconds
    }

    private getScopedKey(key: string): string {
        return `mcp:user:${this.scope}:${key}`
    }

    async get<K extends keyof T>(key: K): Promise<T[K] | undefined> {
        const scopedKey = this.getScopedKey(key as string)
        const value = await this.redis.get(scopedKey)
        if (value === null) {
            return undefined
        }
        return JSON.parse(value)
    }

    async set<K extends keyof T>(key: K, value: T[K]): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.setex(scopedKey, this.ttlSeconds, JSON.stringify(value))
    }

    async delete<K extends keyof T>(key: K): Promise<void> {
        const scopedKey = this.getScopedKey(key as string)
        await this.redis.del(scopedKey)
    }

    async clear(): Promise<void> {
        const pattern = `mcp:user:${this.scope}:*`
        const keys = await this.redis.keys(pattern)
        if (keys.length > 0) {
            await this.redis.del(...keys)
        }
    }
}
