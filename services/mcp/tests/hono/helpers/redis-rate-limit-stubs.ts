export interface RedisRateLimitStubs {
    incr: (key: string) => Promise<number>
    incrby: (key: string, increment: number) => Promise<number>
    expire: (key: string, seconds: number) => Promise<number>
    ttl: (key: string) => Promise<number>
    eval: (script: string, numberOfKeys: number, ...args: (string | number)[]) => Promise<unknown>
}

// Trivial in-memory stubs for the counter ops on RedisLike (rate limiting and
// the confirmed-action stash quota). Test files that only need to satisfy the
// interface (no counter assertions of their own) can spread the return value
// into their fake-redis builder.
//
// Pass `store` when the test exercises session context: the service's only EVAL is
// McpSessionRedisStore's compare-and-merge, and without a store-backed stub the
// merge silently no-ops, so session context never persists across requests.
export function makeRedisRateLimitStubs(store?: Map<string, string>): RedisRateLimitStubs {
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
        eval: async (_script, _numberOfKeys, ...args) => {
            if (!store) {
                return null
            }
            const [key, cachedRaw, desiredRaw] = args.map(String)
            const current = JSON.parse(store.get(key!) ?? '{}') as Record<string, string>
            const cached = cachedRaw === '' ? null : (JSON.parse(cachedRaw!) as Record<string, string>)
            const desired = JSON.parse(desiredRaw!) as Record<string, string>
            for (const [field, value] of Object.entries(desired)) {
                if (current[field] === undefined || (cached !== null && current[field] === cached[field])) {
                    current[field] = value
                }
            }
            store.set(key!, JSON.stringify(current))
            return 1
        },
    }
}
