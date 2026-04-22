import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
    FLAG_DEFS_KV_KEY,
    type FlagDefinitionsSnapshot,
    getFlagDefinitions,
    isLocalEvalEnabled,
    refreshFlagDefinitions,
} from '@/lib/flag-cache'

const originalFetch = globalThis.fetch
const fetchMock = vi.fn()

beforeAll(() => {
    ;(globalThis as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch
})
afterAll(() => {
    ;(globalThis as { fetch: typeof fetch }).fetch = originalFetch
})

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
    const get = vi.fn(async (key: string, opts?: { type?: string }) => {
        const raw = store.get(key)
        if (raw === undefined) {
            return null
        }
        if (opts?.type === 'json') {
            return JSON.parse(raw)
        }
        return raw
    })
    const put = vi.fn(async (key: string, value: string) => {
        store.set(key, value)
    })
    return { store, get, put }
}

interface EnvOverrides {
    FLAG_DEFS_KV?: MockKV
    MCP_FLAG_LOCAL_EVAL_KEY?: string
    POSTHOG_ANALYTICS_HOST?: string
    MCP_LOCAL_EVAL_ENABLED?: string
}

function makeEnv(overrides: EnvOverrides = {}): Env {
    const kv = overrides.FLAG_DEFS_KV ?? makeKV()
    const env: Record<string, unknown> = {
        FLAG_DEFS_KV: kv,
        MCP_FLAG_LOCAL_EVAL_KEY: overrides.MCP_FLAG_LOCAL_EVAL_KEY ?? 'phs_test',
        POSTHOG_ANALYTICS_HOST: overrides.POSTHOG_ANALYTICS_HOST ?? 'https://us.posthog.com',
        MCP_LOCAL_EVAL_ENABLED: overrides.MCP_LOCAL_EVAL_ENABLED ?? '1',
    }
    return env as unknown as Env
}

function makeSnapshot(overrides: Partial<FlagDefinitionsSnapshot> = {}): FlagDefinitionsSnapshot {
    return {
        etag: 'W/"abc"',
        fetchedAt: Date.now(),
        flags: [{ key: 'mcp-version-2', active: true, filters: { groups: [{ rollout_percentage: 50 }] } }],
        groupTypeMapping: {},
        ...overrides,
    }
}

function getKV(env: Env): MockKV {
    return env.FLAG_DEFS_KV as unknown as MockKV
}

describe('isLocalEvalEnabled', () => {
    it('requires the env flag, KV binding, and secret', () => {
        expect(isLocalEvalEnabled(makeEnv())).toBe(true)
        expect(isLocalEvalEnabled(makeEnv({ MCP_LOCAL_EVAL_ENABLED: '' }))).toBe(false)
        expect(isLocalEvalEnabled(makeEnv({ MCP_FLAG_LOCAL_EVAL_KEY: '' }))).toBe(false)
    })
})

describe('getFlagDefinitions', () => {
    beforeEach(() => {
        fetchMock.mockReset()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

    it('returns a fresh snapshot without fetching', async () => {
        const fresh = makeSnapshot({ fetchedAt: Date.now() - 60_000 }) // 1 min old
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: fresh })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        const snap = await getFlagDefinitions(env)
        expect(snap).toEqual(fresh)
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it('returns stale snapshot and triggers background refresh via ctx.waitUntil', async () => {
        const stale = makeSnapshot({ fetchedAt: Date.now() - 10 * 60_000 }) // 10 min old
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: stale })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(
            new Response(JSON.stringify({ flags: [{ key: 'new-flag', active: true }] }), {
                status: 200,
                headers: { etag: 'W/"new"' },
            })
        )

        const waitUntil = vi.fn()
        const snap = await getFlagDefinitions(env, { waitUntil })

        expect(snap).toEqual(stale)
        expect(waitUntil).toHaveBeenCalledOnce()
        const bgPromise = waitUntil.mock.calls[0]?.[0] as Promise<unknown>
        await bgPromise
        expect(fetchMock).toHaveBeenCalledOnce()
        const storedRaw = kv.store.get(FLAG_DEFS_KV_KEY)
        expect(storedRaw).not.toBeUndefined()
        const stored = JSON.parse(storedRaw as string) as FlagDefinitionsSnapshot
        expect(stored.flags[0]?.key).toBe('new-flag')
    })

    it('on KV miss, fetches synchronously and writes through', async () => {
        const kv = makeKV()
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(
            new Response(JSON.stringify({ flags: [{ key: 'mcp-version-2', active: true }] }), {
                status: 200,
                headers: { etag: 'W/"x"' },
            })
        )

        const snap = await getFlagDefinitions(env)
        expect(snap?.flags[0]?.key).toBe('mcp-version-2')
        expect(fetchMock).toHaveBeenCalledOnce()
        expect(kv.put).toHaveBeenCalledOnce()
    })

    it('returns null when KV binding is missing', async () => {
        const env = { MCP_LOCAL_EVAL_ENABLED: '1' } as unknown as Env
        expect(await getFlagDefinitions(env)).toBeNull()
    })
})

describe('refreshFlagDefinitions', () => {
    beforeEach(() => {
        fetchMock.mockReset()
    })

    it('sends Authorization and If-None-Match headers', async () => {
        const prior = makeSnapshot({ etag: 'W/"prior"' })
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: prior })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(
            new Response(JSON.stringify({ flags: [] }), { status: 200, headers: { etag: 'W/"new"' } })
        )

        await refreshFlagDefinitions(env)
        expect(fetchMock).toHaveBeenCalledOnce()
        const call = fetchMock.mock.calls[0]
        expect(call).not.toBeUndefined()
        const [url, init] = call as [string, RequestInit]
        expect(url).toContain('/api/feature_flag/local_evaluation/')
        const headers = init.headers as Record<string, string>
        expect(headers.Authorization).toBe('Bearer phs_test')
        expect(headers['If-None-Match']).toBe('W/"prior"')
    })

    it('preserves flags and bumps fetchedAt on 304', async () => {
        const prior = makeSnapshot({ etag: 'W/"same"', fetchedAt: 0 })
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: prior })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(new Response(null, { status: 304 }))

        const snap = await refreshFlagDefinitions(env)
        expect(snap?.flags).toEqual(prior.flags)
        expect(snap?.fetchedAt).toBeGreaterThan(prior.fetchedAt)
    })

    it('returns prior snapshot on upstream 5xx', async () => {
        const prior = makeSnapshot({ etag: 'W/"ok"' })
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: prior })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(new Response('boom', { status: 503 }))

        const snap = await refreshFlagDefinitions(env)
        expect(snap).toEqual(prior)
        expect(getKV(env).put).not.toHaveBeenCalled()
    })

    it('returns prior snapshot on auth error (401)', async () => {
        const prior = makeSnapshot()
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: prior })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockResolvedValue(new Response('nope', { status: 401 }))

        const snap = await refreshFlagDefinitions(env)
        expect(snap).toEqual(prior)
    })

    it('returns prior snapshot when fetch throws', async () => {
        const prior = makeSnapshot()
        const kv = makeKV({ [FLAG_DEFS_KV_KEY]: prior })
        const env = makeEnv({ FLAG_DEFS_KV: kv })

        fetchMock.mockRejectedValue(new Error('network down'))

        const snap = await refreshFlagDefinitions(env)
        expect(snap).toEqual(prior)
    })

    it('returns null when no secret or host is configured', async () => {
        expect(await refreshFlagDefinitions(makeEnv({ MCP_FLAG_LOCAL_EVAL_KEY: '' }))).toBeNull()
        expect(await refreshFlagDefinitions(makeEnv({ POSTHOG_ANALYTICS_HOST: '' }))).toBeNull()
    })
})
