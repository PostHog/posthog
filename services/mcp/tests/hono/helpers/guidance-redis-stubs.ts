import type { RedisLike } from '@/hono/cache/RedisCache'

export interface GuidanceRedisStub extends RedisLike {
    store: Map<string, string>
    evalCalls: (string | number)[][]
}

export function makeGuidanceRedis(failing = false): GuidanceRedisStub {
    const store = new Map<string, string>()
    const evalCalls: (string | number)[][] = []
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
        get: (key) => guard(store.get(key) ?? null),
        set: (key, value) => {
            store.set(key, value)
            return guard('OK')
        },
        del: async (...keys) => keys.filter((key) => store.delete(key)).length,
        scan: async () => ['0', []],
        incr: (key) => guard(incr(key)),
        expire: () => guard(1),
        ttl: () => guard(-1),
        eval: (_script, _numberOfKeys, ...args) => {
            evalCalls.push(args)
            const [matchedKey, suppressedKey, shownKey, _ttl, threshold, maxPerSession, mode, canFire] =
                args.map(String)
            if (mode === 'suppress') {
                store.set(suppressedKey!, '1')
                return guard(0)
            }
            const matched = incr(matchedKey!)
            if (canFire !== '1' || matched < Number(threshold)) {
                return guard(0)
            }
            if (incr(shownKey!) > Number(maxPerSession)) {
                return guard(0)
            }
            return guard(store.has(suppressedKey!) ? 2 : 1)
        },
    }
}
