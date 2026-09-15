import calculateSlot from 'cluster-key-slot'
import { vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'

export function makeSharedBlobRedisStubs(store: Map<string, string>): Pick<RedisLike, 'ttl' | 'expire' | 'eval'> {
    return {
        ttl: vi.fn(async (key: string) => (store.has(key) ? 60 : -2)),
        expire: vi.fn(async (key: string) => (store.has(key) ? 1 : 0)),
        eval: vi.fn(async (_script: string, numberOfKeys: number, ...args: (string | number)[]) => {
            assertSingleSlot(args.slice(0, numberOfKeys).map(String))
            if (numberOfKeys === 1) {
                const [key, token] = args.map(String)
                return store.get(key!) === token ? Number(store.delete(key!)) : 0
            }
            const [key, blobKey, expected, replacement] = args.map(String)
            if (store.get(key!) !== expected || !store.has(blobKey!)) {
                return 0
            }
            store.set(key!, replacement!)
            return 1
        }),
    }
}

// Redis Cluster rejects a multi-key command unless every key hashes to one slot.
function assertSingleSlot(keys: string[]): void {
    if (new Set(keys.map((key) => calculateSlot(key))).size > 1) {
        throw new Error("CROSSSLOT Keys in request don't hash to the same slot")
    }
}
