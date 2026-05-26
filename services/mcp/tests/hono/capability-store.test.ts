import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RedisLike } from '@/hono/cache/RedisCache'
import { CapabilityStore, projectClientCapabilities, supportsAnyElicitation } from '@/hono/capability-store'

interface MockRedis extends RedisLike {
    _store: Map<string, { value: string; ttl: number }>
    _failNext: { get: number; set: number }
}

function createMockRedis(): MockRedis {
    const store = new Map<string, { value: string; ttl: number }>()
    const failNext = { get: 0, set: 0 }
    return {
        get: vi.fn(async (key: string) => {
            if (failNext.get > 0) {
                failNext.get--
                throw new Error('mock redis get failure')
            }
            return store.get(key)?.value ?? null
        }),
        set: vi.fn(async (key: string, value: string, _ex: string, ttl: number) => {
            if (failNext.set > 0) {
                failNext.set--
                throw new Error('mock redis set failure')
            }
            store.set(key, { value, ttl })
            return 'OK'
        }),
        del: vi.fn(async () => 0),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        incr: vi.fn(async () => 1),
        expire: vi.fn(async () => 1),
        ttl: vi.fn(async () => -1),
        _store: store,
        _failNext: failNext,
    }
}

describe('CapabilityStore', () => {
    let redis: MockRedis

    beforeEach(() => {
        redis = createMockRedis()
    })

    it('returns undefined for an unknown userHash', async () => {
        const store = new CapabilityStore(redis)
        await expect(store.get('hash-1')).resolves.toBeUndefined()
    })

    it('round-trips a stored capability', async () => {
        const store = new CapabilityStore(redis)
        await store.set('hash-1', { elicitation: { form: {} } })
        await expect(store.get('hash-1')).resolves.toEqual({ elicitation: { form: {} } })
    })

    it('writes with the configured TTL', async () => {
        const store = new CapabilityStore(redis, { ttlSeconds: 60 })
        await store.set('hash-2', { elicitation: {} })
        expect(redis._store.get('mcp:client-caps:hash-2')?.ttl).toBe(60)
    })

    it('falls back to 24h TTL by default', async () => {
        const store = new CapabilityStore(redis)
        await store.set('hash-3', { elicitation: {} })
        expect(redis._store.get('mcp:client-caps:hash-3')?.ttl).toBe(24 * 60 * 60)
    })

    it('returns undefined when Redis GET fails (does not throw)', async () => {
        redis._failNext.get = 1
        const store = new CapabilityStore(redis)
        await expect(store.get('hash-1')).resolves.toBeUndefined()
    })

    it('swallows Redis SET failures so initialize never fails on the cache', async () => {
        redis._failNext.set = 1
        const store = new CapabilityStore(redis)
        await expect(store.set('hash-1', { elicitation: {} })).resolves.toBeUndefined()
    })

    it('treats corrupt JSON in storage as a miss', async () => {
        redis._store.set('mcp:client-caps:hash-bad', { value: '{not-json', ttl: 60 })
        const store = new CapabilityStore(redis)
        await expect(store.get('hash-bad')).resolves.toBeUndefined()
    })

    it('isolates entries by userHash', async () => {
        const store = new CapabilityStore(redis)
        await store.set('alice', { elicitation: { form: {} } })
        await store.set('bob', { elicitation: { url: {} } })
        await expect(store.get('alice')).resolves.toEqual({ elicitation: { form: {} } })
        await expect(store.get('bob')).resolves.toEqual({ elicitation: { url: {} } })
    })
})

describe('projectClientCapabilities', () => {
    it('returns an empty projection for non-object input (still writable to cache)', () => {
        expect(projectClientCapabilities(null)).toEqual({})
        expect(projectClientCapabilities('nope')).toEqual({})
        expect(projectClientCapabilities(undefined)).toEqual({})
    })

    it('returns an empty projection when there is no elicitation key', () => {
        // Important: we always return a value so the dispatcher overwrites
        // stale cache entries on every initialize. Returning undefined would
        // skip the SET and leak a prior session's capabilities into a
        // re-initialize with fewer capabilities.
        expect(projectClientCapabilities({ sampling: {} })).toEqual({})
    })

    it('preserves the spec-defined empty elicitation as form-only', () => {
        expect(projectClientCapabilities({ elicitation: {} })).toEqual({ elicitation: {} })
    })

    it('extracts form mode when declared', () => {
        expect(projectClientCapabilities({ elicitation: { form: {} } })).toEqual({
            elicitation: { form: {} },
        })
    })

    it('extracts url mode when declared', () => {
        expect(projectClientCapabilities({ elicitation: { url: {} } })).toEqual({
            elicitation: { url: {} },
        })
    })

    it('extracts both modes when declared', () => {
        expect(projectClientCapabilities({ elicitation: { form: {}, url: {} } })).toEqual({
            elicitation: { form: {}, url: {} },
        })
    })

    it('ignores unknown elicitation sub-keys', () => {
        expect(projectClientCapabilities({ elicitation: { form: {}, junk: {} } })).toEqual({
            elicitation: { form: {} },
        })
    })

    it('ignores non-object elicitation sub-keys', () => {
        expect(projectClientCapabilities({ elicitation: { form: 'yes' } })).toEqual({
            elicitation: {},
        })
    })
})

describe('supportsAnyElicitation', () => {
    it('returns false for undefined caps', () => {
        expect(supportsAnyElicitation(undefined)).toBe(false)
    })

    it('returns false when elicitation key is absent', () => {
        expect(supportsAnyElicitation({})).toBe(false)
    })

    it('returns true for empty elicitation (spec form-mode default)', () => {
        expect(supportsAnyElicitation({ elicitation: {} })).toBe(true)
    })

    it('returns true when form mode is declared', () => {
        expect(supportsAnyElicitation({ elicitation: { form: {} } })).toBe(true)
    })

    it('returns true when url mode is declared', () => {
        expect(supportsAnyElicitation({ elicitation: { url: {} } })).toBe(true)
    })
})
