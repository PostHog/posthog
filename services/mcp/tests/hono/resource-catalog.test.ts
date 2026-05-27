import { beforeEach, describe, expect, it, vi } from 'vitest'

const {
    mockBodyReadsInc,
    mockCacheEventsInc,
    mockManifestEntriesSet,
    mockRevalidationDurationStartTimer,
    mockRevalidationDurationStop,
    mockRevalidationsInc,
} = vi.hoisted(() => {
    const stop = vi.fn()
    return {
        mockBodyReadsInc: vi.fn(),
        mockCacheEventsInc: vi.fn(),
        mockManifestEntriesSet: vi.fn(),
        mockRevalidationDurationStartTimer: vi.fn(() => stop),
        mockRevalidationDurationStop: stop,
        mockRevalidationsInc: vi.fn(),
    }
})

vi.mock('@/hono/metrics', () => ({
    contextMillBodyReadsTotal: { inc: mockBodyReadsInc },
    contextMillCacheEventsTotal: { inc: mockCacheEventsInc },
    contextMillManifestEntries: { set: mockManifestEntriesSet },
    contextMillRevalidationDurationSeconds: { startTimer: mockRevalidationDurationStartTimer },
    contextMillRevalidationsTotal: { inc: mockRevalidationsInc },
}))

vi.mock('@/resources/internals', () => ({
    fetchAndExtractEntries: vi.fn(),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn(),
}))

vi.mock('@/resources/ui-apps.generated', async (importOriginal) => importOriginal())
vi.mock('@/resources/ui-apps', async (importOriginal) => importOriginal())

import type { RedisLike } from '@/hono/cache/RedisCache'
import { ResourceCatalog } from '@/hono/resource-catalog'
import { getPromptsFromManifest } from '@/resources'
import { fetchAndExtractEntries } from '@/resources/internals'
import type { ContextMillResource } from '@/resources/manifest-types'

import { makeRedisRateLimitStubs } from './helpers/redis-rate-limit-stubs'

const mockEnv = {
    MCP_APPS_BASE_URL: 'https://apps.test',
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
} as any

interface MockRedis extends RedisLike {
    _store: Map<string, string>
}

function createMockRedis(): MockRedis {
    const store = new Map<string, string>()
    return {
        get: vi.fn(async (key: string) => store.get(key) ?? null),
        set: vi.fn(async (key: string, value: string, ...args: (string | number)[]) => {
            const isNx = args.includes('NX')
            if (isNx && store.has(key)) {
                return null
            }
            store.set(key, value)
            return 'OK'
        }),
        del: vi.fn(async (...keys: string[]) => {
            let count = 0
            for (const k of keys) {
                if (store.delete(k)) {
                    count++
                }
            }
            return count
        }),
        scan: vi.fn(async () => ['0', []] as [string, string[]]),
        ...makeRedisRateLimitStubs(),
        _store: store,
    }
}

function makeEntry(suffix: string): ContextMillResource {
    return {
        id: `id-${suffix}`,
        name: `name-${suffix}`,
        uri: `posthog://${suffix}`,
        resource: {
            mimeType: 'text/plain',
            description: `${suffix} desc`,
            text: `content of ${suffix}`,
        },
    }
}

const MANIFEST_BYTES_KEY = 'mcp:shared-blob:context-mill:manifest:bytes'
const MANIFEST_FRESH_KEY = 'mcp:shared-blob:context-mill:manifest:fresh'

describe('ResourceCatalog', () => {
    let redis: MockRedis

    beforeEach(() => {
        vi.clearAllMocks()
        mockRevalidationDurationStop.mockClear()
        redis = createMockRedis()
    })

    describe('warmup and resource listing', () => {
        it('serves slim metadata for context-mill resources after warmup', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([makeEntry('guide'), makeEntry('faq')])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                {
                    name: 'greet',
                    title: 'Greet',
                    description: 'A greeting',
                    messages: [{ role: 'user', content: { type: 'text', text: 'hi' } }],
                },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const { resources } = catalog.getResourcesList()
            const names = resources.map((r) => r.name)
            expect(names).toContain('name-guide')
            expect(names).toContain('name-faq')
            // List endpoint must not carry body text.
            expect(resources.every((r) => !('text' in r))).toBe(true)

            const { prompts } = catalog.getPromptsList()
            expect(prompts).toHaveLength(1)
            expect(prompts[0]!.name).toBe('greet')
            expect(mockRevalidationsInc).toHaveBeenCalledWith({
                source: 'warmup',
                status: 'success',
                result: 'cold_refresh',
            })
            expect(mockRevalidationDurationStartTimer).toHaveBeenCalledWith({ source: 'warmup' })
            expect(mockRevalidationDurationStop).toHaveBeenCalledWith({ source: 'warmup', status: 'success' })
            expect(mockManifestEntriesSet).toHaveBeenCalledWith(2)
        })

        it('pre-merges resource list so getResourcesList returns a stable array', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([makeEntry('a')])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const list1 = catalog.getResourcesList().resources
            const list2 = catalog.getResourcesList().resources
            expect(list1).toBe(list2)
        })

        it('revalidates context-mill resources on demand', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValueOnce([makeEntry('old')])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            redis._store.delete(MANIFEST_BYTES_KEY)
            redis._store.delete(MANIFEST_FRESH_KEY)
            vi.mocked(fetchAndExtractEntries).mockResolvedValueOnce([makeEntry('new')])

            await catalog.revalidateContextMillResources('initialize')

            const names = catalog.getResourcesList().resources.map((r) => r.name)
            expect(names).toContain('name-new')
            expect(names).not.toContain('name-old')
            expect(mockRevalidationsInc).toHaveBeenCalledWith({
                source: 'initialize',
                status: 'success',
                result: 'cold_refresh',
            })
        })

        it('keeps existing context-mill resources when revalidation fails', async () => {
            const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
            try {
                vi.mocked(fetchAndExtractEntries).mockResolvedValueOnce([makeEntry('stable')])
                vi.mocked(getPromptsFromManifest).mockResolvedValue([])

                const catalog = new ResourceCatalog(mockEnv, redis)
                await catalog.warmup()

                redis._store.delete(MANIFEST_BYTES_KEY)
                redis._store.delete(MANIFEST_FRESH_KEY)
                vi.mocked(fetchAndExtractEntries).mockRejectedValueOnce(new Error('network'))

                await catalog.revalidateContextMillResources('initialize')

                expect(catalog.getResourcesList().resources.map((r) => r.name)).toContain('name-stable')
                expect(mockRevalidationsInc).toHaveBeenCalledWith({
                    source: 'initialize',
                    status: 'error',
                    result: 'error',
                })
                expect(mockRevalidationDurationStop).toHaveBeenCalledWith({ source: 'initialize', status: 'error' })
                expect(consoleError).toHaveBeenCalledWith(
                    '[ResourceCatalog] Failed to revalidate context-mill resources:',
                    expect.any(Error)
                )
            } finally {
                consoleError.mockRestore()
            }
        })
    })

    describe('readResource', () => {
        it('lazy-loads a context-mill body from Redis on first read', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([makeEntry('doc')])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const result = await catalog.readResource({ uri: 'posthog://doc' })
            expect(result.contents).toHaveLength(1)
            const content = result.contents[0]! as { uri: string; text: string; mimeType: string }
            expect(content.text).toBe('content of doc')
            expect(content.uri).toBe('posthog://doc')
        })

        it('returns empty contents for unknown URI', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const result = await catalog.readResource({ uri: 'posthog://nonexistent' })
            expect(result.contents).toEqual([])
        })

        it('returns empty contents when a body has aged out without triggering a refresh', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([makeEntry('doc')])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            // Drop the body key. The read should acknowledge the removal —
            // the resource has aged out — without triggering any upstream
            // refresh. The slim manifest is left in place; the LLM client's
            // context-window cache is the source of truth for what it knows.
            for (const key of Array.from(redis._store.keys())) {
                if (key.startsWith('mcp:shared-blob:context-mill:body:')) {
                    redis._store.delete(key)
                }
            }
            vi.mocked(fetchAndExtractEntries).mockClear()

            const result = await catalog.readResource({ uri: 'posthog://doc' })
            expect(result.contents).toEqual([])

            // No refresh fired on the miss path.
            await new Promise((r) => setTimeout(r, 20))
            expect(vi.mocked(fetchAndExtractEntries)).not.toHaveBeenCalled()
        })
    })

    describe('getPrompt', () => {
        it('returns messages for a known prompt name', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                {
                    name: 'test-prompt',
                    title: 'T',
                    description: 'D',
                    messages: [{ role: 'user', content: { type: 'text', text: 'hello' } }],
                },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const result = catalog.getPrompt({ name: 'test-prompt' })
            expect(result.messages).toHaveLength(1)
        })

        it('returns empty messages for unknown prompt', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const result = catalog.getPrompt({ name: 'nope' })
            expect(result.messages).toEqual([])
        })
    })

    describe('error resilience', () => {
        it('continues serving prompts when resource fetch fails', async () => {
            vi.mocked(fetchAndExtractEntries).mockRejectedValue(new Error('network'))
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                { name: 'p', title: 'P', description: 'D', messages: [] },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            const names = catalog.getResourcesList().resources.map((r) => r.name)
            expect(names).not.toContain('name-guide')
            expect(catalog.getPromptsList().prompts).toHaveLength(1)
        })

        it('continues serving resources when prompt fetch fails', async () => {
            vi.mocked(fetchAndExtractEntries).mockResolvedValue([makeEntry('r')])
            vi.mocked(getPromptsFromManifest).mockRejectedValue(new Error('fail'))

            const catalog = new ResourceCatalog(mockEnv, redis)
            await catalog.warmup()

            expect(catalog.getResourcesList().resources.map((r) => r.name)).toContain('name-r')
            expect(catalog.getPromptsList().prompts).toEqual([])
        })
    })
})
