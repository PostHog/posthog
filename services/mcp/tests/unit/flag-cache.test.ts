import type { FlagDefinitionCacheData } from 'posthog-node/experimental'
import { describe, expect, it, vi } from 'vitest'

import {
    CloudflareKVFlagCacheReader,
    CloudflareKVFlagCacheWriter,
    isLocalEvalConfigured,
    isLocalEvalEnabled,
} from '@/lib/flag-cache'

interface MockKV {
    store: Map<string, string>
    get: ReturnType<typeof vi.fn>
    put: ReturnType<typeof vi.fn>
}

function makeKV(initial?: Record<string, unknown>): MockKV {
    const store = new Map<string, string>()
    if (initial) {
        for (const [k, v] of Object.entries(initial)) {
            store.set(k, typeof v === 'string' ? v : JSON.stringify(v))
        }
    }
    const get = vi.fn(async (key: string) => store.get(key) ?? null)
    const put = vi.fn(async (key: string, value: string) => {
        store.set(key, value)
    })
    return { store, get, put }
}

function asKVNamespace(kv: MockKV): KVNamespace {
    return kv as unknown as KVNamespace
}

const TEAM_KEY = 'phc_team123'
const EXPECTED_KEY = `posthog:flags:${TEAM_KEY}`

function sampleData(): FlagDefinitionCacheData {
    return {
        flags: [{ id: 1, key: 'mcp-version-2', active: true, filters: { groups: [] } } as never],
        groupTypeMapping: {},
        cohorts: {},
    }
}

describe('CloudflareKVFlagCacheReader', () => {
    it('reads and parses cached definitions using the team-scoped key', async () => {
        const data = sampleData()
        const kv = makeKV({ [EXPECTED_KEY]: data })
        const reader = new CloudflareKVFlagCacheReader(asKVNamespace(kv), TEAM_KEY)

        const result = await reader.getFlagDefinitions()
        expect(result).toEqual(data)
        expect(kv.get).toHaveBeenCalledWith(EXPECTED_KEY, { cacheTtl: 60 })
    })

    it('returns undefined when the cache is empty', async () => {
        const kv = makeKV()
        const reader = new CloudflareKVFlagCacheReader(asKVNamespace(kv), TEAM_KEY)
        expect(await reader.getFlagDefinitions()).toBeUndefined()
    })

    it('returns undefined when the cached blob is malformed JSON', async () => {
        const kv = makeKV()
        kv.store.set(EXPECTED_KEY, 'not json {')
        const reader = new CloudflareKVFlagCacheReader(asKVNamespace(kv), TEAM_KEY)
        expect(await reader.getFlagDefinitions()).toBeUndefined()
    })

    it('never signals a fetch', () => {
        const reader = new CloudflareKVFlagCacheReader(asKVNamespace(makeKV()), TEAM_KEY)
        expect(reader.shouldFetchFlagDefinitions()).toBe(false)
    })

    it('throws if the SDK attempts to write', async () => {
        const reader = new CloudflareKVFlagCacheReader(asKVNamespace(makeKV()), TEAM_KEY)
        await expect(reader.onFlagDefinitionsReceived()).rejects.toThrow(/read-only/)
    })
})

describe('CloudflareKVFlagCacheWriter', () => {
    it('always reports empty cache to force a fresh fetch', async () => {
        const kv = makeKV({ [EXPECTED_KEY]: sampleData() })
        const writer = new CloudflareKVFlagCacheWriter(asKVNamespace(kv), TEAM_KEY)
        expect(await writer.getFlagDefinitions()).toBeUndefined()
    })

    it('signals the SDK to fetch', () => {
        const writer = new CloudflareKVFlagCacheWriter(asKVNamespace(makeKV()), TEAM_KEY)
        expect(writer.shouldFetchFlagDefinitions()).toBe(true)
    })

    it('persists received definitions under the team-scoped key', async () => {
        const kv = makeKV()
        const writer = new CloudflareKVFlagCacheWriter(asKVNamespace(kv), TEAM_KEY)
        const data = sampleData()

        await writer.onFlagDefinitionsReceived(data)

        expect(kv.put).toHaveBeenCalledWith(EXPECTED_KEY, JSON.stringify(data))
        expect(kv.store.get(EXPECTED_KEY)).toBe(JSON.stringify(data))
    })
})

describe('env guards', () => {
    it('isLocalEvalConfigured requires KV, the secret, and the project key', () => {
        const base = {
            FLAG_DEFS_KV: asKVNamespace(makeKV()),
            MCP_FLAG_LOCAL_EVAL_KEY: 'phs_test',
            POSTHOG_ANALYTICS_API_KEY: 'phc_test',
        } as unknown as Env
        expect(isLocalEvalConfigured(base)).toBe(true)
        expect(isLocalEvalConfigured({ ...base, MCP_FLAG_LOCAL_EVAL_KEY: '' } as Env)).toBe(false)
        expect(isLocalEvalConfigured({ ...base, POSTHOG_ANALYTICS_API_KEY: '' } as Env)).toBe(false)
        expect(isLocalEvalConfigured({ ...base, FLAG_DEFS_KV: undefined } as unknown as Env)).toBe(false)
    })

    it('isLocalEvalEnabled additionally requires MCP_LOCAL_EVAL_ENABLED=1', () => {
        const configured = {
            FLAG_DEFS_KV: asKVNamespace(makeKV()),
            MCP_FLAG_LOCAL_EVAL_KEY: 'phs_test',
            POSTHOG_ANALYTICS_API_KEY: 'phc_test',
        } as unknown as Env
        expect(isLocalEvalEnabled(configured)).toBe(false)
        expect(isLocalEvalEnabled({ ...configured, MCP_LOCAL_EVAL_ENABLED: '1' } as Env)).toBe(true)
        expect(isLocalEvalEnabled({ ...configured, MCP_LOCAL_EVAL_ENABLED: 'true' } as Env)).toBe(false)
    })
})
