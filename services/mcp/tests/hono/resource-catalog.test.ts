import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/resources/internals', () => ({
    fetchContextMillResources: vi.fn(),
    filterValidEntries: vi.fn(),
    loadManifestFromArchive: vi.fn(),
    clearResourceCache: vi.fn(),
}))

vi.mock('@/resources', () => ({
    getPromptsFromManifest: vi.fn(),
}))

vi.mock('@/resources/ui-apps.generated', async (importOriginal) => importOriginal())
vi.mock('@/resources/ui-apps', async (importOriginal) => importOriginal())

import { fetchContextMillResources, filterValidEntries, loadManifestFromArchive } from '@/resources/internals'
import { getPromptsFromManifest } from '@/resources'
import { ResourceCatalog } from '@/hono/resource-catalog'

const mockEnv = {
    MCP_APPS_BASE_URL: 'https://apps.test',
    POSTHOG_MCP_APPS_ANALYTICS_BASE_URL: undefined,
} as any

function makeContextMillEntry(
    name: string,
    uri: string
): { name: string; uri: string; resource: { mimeType: string; description: string; text: string } } {
    return {
        name,
        uri,
        resource: {
            mimeType: 'text/plain',
            description: `${name} desc`,
            text: `content of ${name}`,
        },
    }
}

describe('ResourceCatalog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe('warmup and resource listing', () => {
        it('serves resources and prompts after warmup', async () => {
            const entries = [
                makeContextMillEntry('guide', 'posthog://guide'),
                makeContextMillEntry('faq', 'posthog://faq'),
            ]
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue(entries as any)
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                {
                    name: 'greet',
                    title: 'Greet',
                    description: 'A greeting',
                    messages: [{ role: 'user', content: { type: 'text', text: 'hi' } }],
                },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const { resources } = catalog.getResourcesList()
            expect(resources.map((r) => r.name)).toContain('guide')
            expect(resources.map((r) => r.name)).toContain('faq')

            const { prompts } = catalog.getPromptsList()
            expect(prompts).toHaveLength(1)
            expect(prompts[0]!.name).toBe('greet')
        })

        it('pre-merges resource list so getResourcesList returns a stable array', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([makeContextMillEntry('a', 'posthog://a')] as any)
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const list1 = catalog.getResourcesList().resources
            const list2 = catalog.getResourcesList().resources
            expect(list1).toBe(list2)
        })
    })

    describe('readResource', () => {
        it('returns contents for a known URI', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([makeContextMillEntry('doc', 'posthog://doc')] as any)
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = catalog.readResource({ uri: 'posthog://doc' }) as any
            expect(result.contents).toHaveLength(1)
            expect(result.contents[0].text).toBe('content of doc')
        })

        it('returns empty contents for unknown URI', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = catalog.readResource({ uri: 'posthog://nonexistent' }) as any
            expect(result.contents).toEqual([])
        })
    })

    describe('getPrompt', () => {
        it('returns messages for a known prompt name', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                {
                    name: 'test-prompt',
                    title: 'T',
                    description: 'D',
                    messages: [{ role: 'user', content: { type: 'text', text: 'hello' } }],
                },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = catalog.getPrompt({ name: 'test-prompt' }) as any
            expect(result.messages).toHaveLength(1)
        })

        it('returns empty messages for unknown prompt', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([])
            vi.mocked(getPromptsFromManifest).mockResolvedValue([])

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const result = catalog.getPrompt({ name: 'nope' }) as any
            expect(result.messages).toEqual([])
        })
    })

    describe('error resilience', () => {
        it('continues serving prompts when resource fetch fails', async () => {
            vi.mocked(fetchContextMillResources).mockRejectedValue(new Error('network'))
            vi.mocked(getPromptsFromManifest).mockResolvedValue([
                { name: 'p', title: 'P', description: 'D', messages: [] },
            ] as any)

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            const names = catalog.getResourcesList().resources.map((r) => r.name)
            expect(names).not.toContain('guide')
            expect(catalog.getPromptsList().prompts).toHaveLength(1)
        })

        it('continues serving resources when prompt fetch fails', async () => {
            vi.mocked(fetchContextMillResources).mockResolvedValue('archive' as any)
            vi.mocked(loadManifestFromArchive).mockReturnValue({ resources: [] } as any)
            vi.mocked(filterValidEntries).mockReturnValue([makeContextMillEntry('r', 'posthog://r')] as any)
            vi.mocked(getPromptsFromManifest).mockRejectedValue(new Error('fail'))

            const catalog = new ResourceCatalog(mockEnv)
            await catalog.warmup()

            expect(catalog.getResourcesList().resources.map((r) => r.name)).toContain('r')
            expect(catalog.getPromptsList().prompts).toEqual([])
        })
    })
})
