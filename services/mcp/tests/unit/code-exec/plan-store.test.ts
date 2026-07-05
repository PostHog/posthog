import { describe, expect, it } from 'vitest'

import { MemoryPlanStore, type Plan, type PlanStoreRedis, RedisPlanStore, type StoredPlan } from '@/lib/code-exec'

const PLAN: Plan = {
    mutations: [],
    normalizedMutations: [],
    planHash: 'plan-abc',
    scriptHash: 'script-xyz',
    createdAt: 0,
}

function stored(): StoredPlan {
    return { script: 'export default 1', plan: PLAN, sub: 'did-1' }
}

describe('plan store', () => {
    it('MemoryPlanStore returns a stored plan and expires it on the injected clock', async () => {
        let now = 1000
        const store = new MemoryPlanStore({ now: () => now })
        await store.put('script-xyz', stored(), 60)

        expect(await store.get('script-xyz')).toEqual(stored())
        // Past the 60s TTL the entry is gone — plans must not be applicable forever.
        now += 61_000
        expect(await store.get('script-xyz')).toBeNull()
    })

    it('RedisPlanStore writes with EX ttl and reads back the parsed plan', async () => {
        const backing = new Map<string, string>()
        const observed: { mode?: string; ttl?: number } = {}
        const redis: PlanStoreRedis = {
            set: async (key, value, mode, ttl) => {
                observed.mode = mode
                observed.ttl = ttl
                backing.set(key, value)
                return 'OK'
            },
            get: async (key) => backing.get(key) ?? null,
        }
        const store = new RedisPlanStore(redis)

        await store.put('script-xyz', stored(), 600)
        expect(observed.mode).toBe('EX')
        expect(observed.ttl).toBe(600)
        expect(await store.get('script-xyz')).toEqual(stored())
        expect(await store.get('missing')).toBeNull()
    })
})
