import { describe, expect, it, vi } from 'vitest'

import { ToolInputValidationError } from '@/lib/errors'
import updateInsightVerifyingPersistence from '@/tools/insights/update'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://us.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

const saved = {
    id: 7,
    short_id: 'AaVQ8Ijw',
    name: 'Old name',
    description: 'Old description',
    favorited: false,
    tags: ['old'],
    // A session-authenticated PATCH response omits the deprecated `dashboards` field.
    dashboard_tiles: [{ id: 11, dashboard_id: 1, deleted: false }],
}

describe('insight-update persistence check', () => {
    const tool = updateInsightVerifyingPersistence()

    it.each([
        ['only an id', { id: 7 }],
        ['fields nested under an undeclared key', { id: 7, insight: { name: 'New name' } }],
        ['a misnamed field', { id: 7, title: 'New name' }],
    ])('rejects %s without sending a PATCH', async (_label, input) => {
        const request = vi.fn()

        const params = tool.schema.parse(input)

        await expect(tool.handler(createMockContext(request), params)).rejects.toBeInstanceOf(ToolInputValidationError)
        expect(request).not.toHaveBeenCalled()
    })

    it('reports the requested fields that the saved insight does not hold', async () => {
        const request = vi.fn().mockResolvedValue(saved)

        const params = tool.schema.parse({
            id: 7,
            name: 'New name',
            tags: ['new'],
            description: 'Old description',
            dashboards: [1, 2],
        })

        await expect(tool.handler(createMockContext(request), params)).rejects.toThrow(
            /does not hold the requested value for: name, tags, dashboards\./
        )
    })

    it('returns the insight when the saved values match the API normalization', async () => {
        const request = vi.fn().mockResolvedValue({
            ...saved,
            name: 'New name',
            favorited: true,
            tags: ['growth', 'q3'],
            dashboard_tiles: [
                { id: 12, dashboard_id: 2, deleted: false },
                { id: 11, dashboard_id: 1, deleted: false },
                { id: 13, dashboard_id: 3, deleted: true },
            ],
        })

        const params = tool.schema.parse({
            id: 7,
            name: '  New name ',
            favorited: true,
            tags: ['Q3', ' growth', 'q3'],
            dashboards: [1, 2],
        })
        const result = (await tool.handler(createMockContext(request), params)) as Record<string, unknown>

        expect(result['name']).toBe('New name')
        expect(request).toHaveBeenCalledWith(
            expect.objectContaining({
                method: 'PATCH',
                path: '/api/projects/42/insights/7/',
                body: {
                    name: '  New name ',
                    favorited: true,
                    tags: ['Q3', ' growth', 'q3'],
                    dashboards: [1, 2],
                },
            })
        )
    })
})
