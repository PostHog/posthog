export interface RedisRateLimitStubs {
    incr: (key: string) => Promise<number>
    expire: (key: string, seconds: number) => Promise<number>
    ttl: (key: string) => Promise<number>
}

// Trivial in-memory stubs for the rate-limit ops on RedisLike. Test files that
// only need to satisfy the interface (no rate-limit assertions of their own)
// can spread the return value into their fake-redis builder.
export function makeRedisRateLimitStubs(): RedisRateLimitStubs {
    const counts = new Map<string, number>()
    return {
        incr: async (key) => {
            const next = (counts.get(key) ?? 0) + 1
            counts.set(key, next)
            return next
        },
        expire: async () => 1,
        ttl: async () => 60,
    }
}
