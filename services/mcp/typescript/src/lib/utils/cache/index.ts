import type { Redis } from 'ioredis'

import type { State } from '@/tools/types'

import { MemoryCache } from './MemoryCache'
import { RedisCache } from './RedisCache'
import type { ScopedCache } from './ScopedCache'

export type CacheConfig = {
    redis: Redis | undefined
    ttlSeconds?: number
}

export function createCache(scope: string, config: CacheConfig = { redis: undefined }): ScopedCache<State> {
    if (config.redis) {
        return new RedisCache<State>(scope, config.redis, config.ttlSeconds)
    }
    return new MemoryCache<State>(scope)
}

export { MemoryCache } from './MemoryCache'
export { RedisCache } from './RedisCache'
export { ScopedCache } from './ScopedCache'
