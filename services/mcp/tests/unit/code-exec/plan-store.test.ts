import { promises as fs } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
    FilePlanStore,
    MemoryPlanStore,
    type Plan,
    type PlanStoreRedis,
    RedisPlanStore,
    sha256Hex,
    type StoredPlan,
} from '@/lib/code-exec'

const PLAN: Plan = {
    mutations: [],
    normalizedMutations: [],
    planHash: 'plan-abc',
    scriptHash: 'script-xyz',
    createdAt: 0,
}

const KEY = 'did-1:cat-assistant-tree'

function stored(): StoredPlan {
    return { kind: 'script', script: 'export default 1', plan: PLAN, sub: 'did-1' }
}

interface RedisStub {
    redis: PlanStoreRedis
    backing: Map<string, string>
    setCalls: Array<{ key: string; value: string; mode: string; ttl: number }>
}

function makeRedisStub(options: { withGetdel?: boolean; remainingTtl?: number } = {}): RedisStub {
    const backing = new Map<string, string>()
    const setCalls: RedisStub['setCalls'] = []
    const redis: PlanStoreRedis = {
        set: async (key, value, mode, ttl) => {
            setCalls.push({ key, value, mode, ttl })
            backing.set(key, value)
            return 'OK'
        },
        get: async (key) => backing.get(key) ?? null,
        ttl: async (key) => (backing.has(key) ? (options.remainingTtl ?? 60) : -2),
    }
    if (options.withGetdel) {
        redis.getdel = async (key) => {
            const value = backing.get(key) ?? null
            backing.delete(key)
            return value
        }
    }
    return { redis, backing, setCalls }
}

describe('plan store', () => {
    it('MemoryPlanStore returns a stored plan and expires it on the injected clock', async () => {
        let now = 1000
        const store = new MemoryPlanStore({ now: () => now })
        await store.put(KEY, stored(), 60)

        expect(await store.get(KEY)).toEqual(stored())
        // Past the 60s TTL the entry is gone — plans must not be applicable forever.
        now += 61_000
        expect(await store.get(KEY)).toBeNull()
    })

    it('MemoryPlanStore.consume takes the plan once, tombstones reuse, and expires with the TTL', async () => {
        let now = 1000
        const store = new MemoryPlanStore({ now: () => now })
        await store.put(KEY, stored(), 60)

        expect(await store.consume(KEY)).toEqual(stored())
        // Reuse within the TTL is distinguishable from never-existed — that drives the "already applied" message.
        expect(await store.consume(KEY)).toBe('consumed')
        // The collision check in run() treats consumed keys as free.
        expect(await store.get(KEY)).toBeNull()
        now += 61_000
        expect(await store.consume(KEY)).toBeNull()
        expect(await store.consume('did-1:never-stored-here')).toBeNull()
    })

    it('RedisPlanStore writes with EX ttl and reads back the parsed plan', async () => {
        const { redis, setCalls } = makeRedisStub()
        const store = new RedisPlanStore(redis)

        await store.put(KEY, stored(), 600)
        expect(setCalls[0]).toMatchObject({ mode: 'EX', ttl: 600 })
        expect(await store.get(KEY)).toEqual(stored())
        expect(await store.get('missing')).toBeNull()
    })

    it.each([
        { atomicity: 'GETDEL', withGetdel: true },
        { atomicity: 'get+set fallback', withGetdel: false },
    ])(
        'RedisPlanStore.consume via $atomicity takes the plan once and tombstones reuse with the remaining TTL',
        async ({ withGetdel }) => {
            const { redis, setCalls } = makeRedisStub({ withGetdel, remainingTtl: 42 })
            const store = new RedisPlanStore(redis)
            await store.put(KEY, stored(), 600)

            expect(await store.consume(KEY)).toEqual(stored())
            // The tombstone inherits the remaining TTL so it cannot outlive (or lack) the plan's expiry.
            expect(setCalls.at(-1)).toMatchObject({ value: '{"consumed":true}', mode: 'EX', ttl: 42 })
            expect(await store.consume(KEY)).toBe('consumed')
            expect(await store.get(KEY)).toBeNull()
            expect(await store.consume('did-1:never-stored-here')).toBeNull()
        }
    )

    describe('FilePlanStore (CLI local mode, spec §4.8)', () => {
        let directory: string
        let now: number
        const makeStore = (): FilePlanStore => new FilePlanStore({ directory, now: () => now })

        beforeEach(async () => {
            directory = await fs.mkdtemp(path.join(os.tmpdir(), 'plan-store-test-'))
            now = 1_700_000_000_000
        })

        afterEach(async () => {
            await fs.rm(directory, { recursive: true, force: true })
        })

        it.each([
            { case: 'a plain key', key: KEY },
            // The key embeds a distinct_id, which is arbitrary user-influenced
            // input — none of it may reach the filesystem path.
            { case: 'path-traversal characters in the sub', key: '../../etc/passwd:cat-assistant-tree' },
            { case: 'separators and colons in the sub', key: 'user/4:2\\weird:cat-assistant-tree' },
            { case: 'a unicode sub', key: 'пользователь-💥:cat-assistant-tree' },
        ])('put/get/consume roundtrip with $case stays inside the directory', async ({ key }) => {
            const store = makeStore()
            await store.put(key, stored(), 60)

            // The filename is pure hex the key author never controls.
            const entries = await fs.readdir(directory)
            expect(entries).toHaveLength(1)
            expect(entries[0]).toMatch(/^[0-9a-f]{32}\.json$/)

            expect(await store.get(key)).toEqual(stored())
            expect(await store.consume(key)).toEqual(stored())
            // Reuse hits the tombstone — that drives the "already applied" message.
            expect(await store.consume(key)).toBe('consumed')
            expect(await store.get(key)).toBeNull()
        })

        it('a fresh store over the same directory sees plans and tombstones — CLI invocations are one-shot processes', async () => {
            await makeStore().put(KEY, stored(), 600)
            expect(await makeStore().consume(KEY)).toEqual(stored())
            expect(await makeStore().consume(KEY)).toBe('consumed')
        })

        it('expires records on the clock, deleting the file lazily on read', async () => {
            const store = makeStore()
            await store.put(KEY, stored(), 60)
            now += 61_000
            expect(await store.get(KEY)).toBeNull()
            expect(await fs.readdir(directory)).toHaveLength(0)
            expect(await store.consume(KEY)).toBeNull()
        })

        it('an expired tombstone reads as absent, not as already-applied', async () => {
            const store = makeStore()
            await store.put(KEY, stored(), 60)
            await store.consume(KEY)
            now += 61_000
            expect(await store.consume(KEY)).toBeNull()
        })

        it('put garbage-collects expired sibling records', async () => {
            const store = makeStore()
            await store.put('did-1:old-plan-one', stored(), 60)
            now += 61_000
            await store.put('did-1:new-plan-two', stored(), 60)
            expect(await fs.readdir(directory)).toHaveLength(1)
            expect(await store.get('did-1:new-plan-two')).toEqual(stored())
        })

        it('never returns a record whose stored key differs from the requested one (truncated-hash collision)', async () => {
            const store = makeStore()
            // Craft the collision: a record at KEY's filename that belongs to another key.
            const fileName = `${sha256Hex(KEY).slice(0, 32)}.json`
            await fs.writeFile(
                path.join(directory, fileName),
                JSON.stringify({ key: 'someone-else:other-plan-id', expiresAt: now + 60_000, storedPlan: stored() })
            )
            expect(await store.get(KEY)).toBeNull()
            expect(await store.consume(KEY)).toBeNull()
            // The colliding record belongs to the other key — it must survive.
            expect(await fs.readdir(directory)).toEqual([fileName])
        })
    })
})
