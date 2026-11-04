import type { RedisLike } from '@/hono/cache/RedisCache'

export interface GuidanceRedisStub extends RedisLike {
    store: Map<string, string>
    evalCalls: (string | number)[][]
    /** Moves the stub's clock forward and drops every key whose TTL has run out. */
    advance(seconds: number): void
}

export function makeGuidanceRedis(failing = false): GuidanceRedisStub {
    const store = new Map<string, string>()
    const evalCalls: (string | number)[][] = []
    const expiresAt = new Map<string, number>()
    let now = 0
    const refresh = (keys: (string | undefined)[], ttl: number): void => {
        for (const key of keys) {
            if (key !== undefined && store.has(key)) {
                expiresAt.set(key, now + ttl)
            }
        }
    }
    const guard = async <T>(value: T): Promise<T> => {
        if (failing) {
            throw new Error('redis down')
        }
        return value
    }
    const incr = (key: string): number => {
        const next = Number(store.get(key) ?? 0) + 1
        store.set(key, String(next))
        return next
    }
    return {
        store,
        evalCalls,
        advance: (seconds) => {
            now += seconds
            for (const [key, expiry] of expiresAt) {
                if (expiry <= now) {
                    store.delete(key)
                    expiresAt.delete(key)
                }
            }
        },
        get: (key) => guard(store.get(key) ?? null),
        set: (key, value, ...options) => {
            store.set(key, value)
            if (options[0] === 'EX') {
                refresh([key], Number(options[1]))
            }
            return guard('OK')
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async () => ['0', []],
        incr: (key) => guard(incr(key)),
        expire: () => guard(1),
        ttl: () => guard(-1),
        eval: (_script, _numberOfKeys, ...args) => {
            evalCalls.push(args)
            const [matchedKey, suppressedKey, shownKey, ttlArg, threshold, maxPerSession, mode, canFire] =
                args.map(String)
            const ttl = Number(ttlArg)
            const keys = [matchedKey, suppressedKey, shownKey]
            if (mode === 'suppress') {
                store.set(suppressedKey!, '1')
                refresh(keys, ttl)
                return guard(0)
            }
            const matched = incr(matchedKey!)
            if (mode === 'mirror') {
                if (canFire === '1') {
                    incr(shownKey!)
                }
                refresh(keys, ttl)
                return guard(0)
            }
            if (canFire !== '1' || matched < Number(threshold)) {
                refresh(keys, ttl)
                return guard(0)
            }
            const shown = incr(shownKey!)
            refresh(keys, ttl)
            if (shown > Number(maxPerSession)) {
                return guard(0)
            }
            return guard(store.has(suppressedKey!) ? 2 : 1)
        },
    }
}
