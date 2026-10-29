import type { RedisLike } from '@/hono/cache/RedisCache'

import { makeRedisRateLimitStubs } from './redis-rate-limit-stubs'

export function createInMemoryRedis(): RedisLike & {
    ping(): Promise<string>
    incrby(key: string, increment: number): Promise<number>
} {
    const store = new Map<string, string>()
    return {
        get: async (key) => store.get(key) ?? null,
        set: async (key, value, ...args) => {
            if (args.includes('NX') && store.has(key)) {
                return null
            }
            store.set(key, String(value))
            return 'OK'
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async (_cursor, ...args) => {
            const match = args.indexOf('MATCH')
            const prefix = match === -1 ? '' : String(args[match + 1]).replace(/\*$/, '')
            return ['0', Array.from(store.keys()).filter((key) => key.startsWith(prefix))] as [string, string[]]
        },
        ...makeRedisRateLimitStubs(store),
        ping: async () => 'PONG',
    }
}
