import { describe, expect, it, vi } from 'vitest'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/ai_observability'
import type { Context } from '@/tools/types'

function createContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({ count: 1, results: [{ id: 'resource-id', tags: ['quality', 'a,b'] }] })
    return {
        request,
        context: {
            api: { request, getProjectBaseUrl: () => 'https://example.com/project/17' },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('17') },
            env: { POSTHOG_PUBLIC_URL: 'https://example.com' },
        } as unknown as Context,
    }
}

describe('AI resource tag tool contracts', () => {
    it.each([
        ['llma-dataset-list', '/api/projects/17/datasets/', {}],
        ['llma-score-definition-list', '/api/projects/17/llm_analytics/score_definitions/', {}],
        ['llma-offline-experiment-list', '/api/projects/17/ai_observability/offline_experiments/', {}],
        [
            'llma-offline-scorer-history',
            '/api/projects/17/ai_observability/offline_scorers/scorer-id/history/',
            { id: 'scorer-id' },
        ],
    ])('%s forwards AND/OR tag filters and retains tags in its response', async (name, path, parameters) => {
        const tool = getToolByName(GENERATED_TOOLS, name)
        const { context, request } = createContext()
        for (const tag_match of ['any', 'all']) {
            const query = { tags: '["quality","a,b"]', tag_match }
            const parsed = tool.schema.parse({ ...parameters, ...query })
            const result = await tool.handler(context, parsed)
            expect(request).toHaveBeenLastCalledWith(
                expect.objectContaining({ method: 'GET', path, query: expect.objectContaining(query) })
            )
            expect(JSON.stringify(result)).toContain('"tags":["quality","a,b"]')
        }
    })

    it('requires an explicit tag replacement when updating an experiment', async () => {
        const tool = getToolByName(GENERATED_TOOLS, 'llma-offline-experiment-update')
        expect(tool.schema.safeParse({ id: 'resource-id' }).success).toBe(false)
        const { context, request } = createContext()
        await tool.handler(context, tool.schema.parse({ id: 'resource-id', tags: [] }))
        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'PATCH',
                path: '/api/projects/17/ai_observability/offline_experiments/resource-id/',
                body: { tags: [] },
            })
        )
    })
})
