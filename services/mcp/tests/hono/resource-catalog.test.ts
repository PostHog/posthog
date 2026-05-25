import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/resources/kv-store', () => ({
    getManifest: vi.fn(),
    getResourceText: vi.fn(),
}))

vi.mock('@/resources/ui-apps.generated', async (importOriginal) => importOriginal())
vi.mock('@/resources/ui-apps', async (importOriginal) => importOriginal())

import { ResourceCatalog } from '@/hono/resource-catalog'
import { getManifest, getResourceText } from '@/resources/kv-store'

const mockEnv = {
    MCP_APPS_BASE_URL: 'https://apps.test',
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
} as any

function makeContextMillEntry(
    id: string,
    name: string,
    uri: string
): { id: string; name: string; uri: string; resource: { mimeType: string; description: string; text: string } } {
    return {
        id,
        name,
        uri,
        resource: {
            mimeType: 'text/plain',
            description: `${name} desc`,
            text: `content of ${name}`,
        },
    }
}

function mockManifestWith(entries: ReturnType<typeof makeContextMillEntry>[]): void {
    vi.mocked(getManifest).mockResolvedValue({ version: 'v1.test', resources: entries as any } as any)
}

describe('ResourceCatalog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        // Default: getResourceText echoes inline text so tests don't need to stub it explicitly.
        vi.mocked(getResourceText).mockImplementation(async (_env, _version, entry) => entry.resource.text)
    })

    describe('warmup and resource listing', () => {
        it('serves resources after warmup', async () => {
            mockManifestWith([
                makeContextMillEntry('guide-id', 'guide', 'posthog://guide'),
                makeContextMillEntry('faq-id', 'faq', 'posthog://faq'),
            ])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const { resources } = catalog.getResourcesList()
            expect(resources.map((r) => r.name)).toContain('guide')
            expect(resources.map((r) => r.name)).toContain('faq')
        })

        it('pre-merges resource list so getResourcesList returns a stable array', async () => {
            mockManifestWith([makeContextMillEntry('a-id', 'a', 'posthog://a')])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const list1 = catalog.getResourcesList().resources
            const list2 = catalog.getResourcesList().resources
            expect(list1).toBe(list2)
        })

        it('does not pre-materialize resource text — lazy fetch happens on read', async () => {
            mockManifestWith([makeContextMillEntry('doc-id', 'doc', 'posthog://doc')])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            expect(getResourceText).not.toHaveBeenCalled()
        })
    })

    describe('readResource', () => {
        it('returns contents for a known URI by calling getResourceText with the manifest version', async () => {
            mockManifestWith([makeContextMillEntry('doc-id', 'doc', 'posthog://doc')])
            vi.mocked(getResourceText).mockResolvedValue('lazy-fetched-text')

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = (await catalog.readResource({ uri: 'posthog://doc' })) as any
            expect(result.contents).toHaveLength(1)
            expect(result.contents[0].text).toBe('lazy-fetched-text')
            expect(getResourceText).toHaveBeenCalledWith(
                mockEnv,
                'v1.test',
                expect.objectContaining({ id: 'doc-id', uri: 'posthog://doc' })
            )
        })

        it('returns empty contents for unknown URI without calling getResourceText', async () => {
            mockManifestWith([])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = (await catalog.readResource({ uri: 'posthog://nonexistent' })) as any
            expect(result.contents).toEqual([])
            expect(getResourceText).not.toHaveBeenCalled()
        })
    })

    describe('prompts (placeholder)', () => {
        // The prompt source was removed; the dispatcher still routes these
        // methods so the catalog must answer with well-formed empty results.
        it('getPromptsList returns empty prompts array', async () => {
            mockManifestWith([])
            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()
            expect(catalog.getPromptsList()).toEqual({ prompts: [] })
        })

        it('getPrompt returns empty messages regardless of name', async () => {
            mockManifestWith([])
            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()
            expect(catalog.getPrompt({ name: 'anything' })).toEqual({ messages: [] })
        })
    })

    describe('error resilience', () => {
        it('continues serving an empty resource list when manifest fetch fails', async () => {
            vi.mocked(getManifest).mockRejectedValue(new Error('network'))

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const names = catalog.getResourcesList().resources.map((r) => r.name)
            expect(names).not.toContain('guide')
        })
    })
})
