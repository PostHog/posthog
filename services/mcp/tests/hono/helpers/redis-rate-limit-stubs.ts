export interface RedisRateLimitStubs {
    incr: (key: string) => Promise<number>
    incrby: (key: string, increment: number) => Promise<number>
    expire: (key: string, seconds: number) => Promise<number>
    ttl: (key: string) => Promise<number>
}

// Trivial in-memory stubs for the counter ops on RedisLike (rate limiting and
// the confirmed-action stash quota). Test files that only need to satisfy the
// interface (no counter assertions of their own) can spread the return value
// into their fake-redis builder.
export function makeRedisRateLimitStubs(): RedisRateLimitStubs {
    const counts = new Map<string, number>()
    return {
        incr: async (key) => {
            const next = (counts.get(key) ?? 0) + 1
            counts.set(key, next)
            return next
        },
        incrby: async (key, increment) => {
            const next = (counts.get(key) ?? 0) + increment
            counts.set(key, next)
            return next
        },
        expire: async () => 1,
        ttl: async () => 60,
    }
}
