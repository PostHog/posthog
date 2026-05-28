import { beforeEach, describe, expect, it, vi } from 'vitest'

import { isFeatureFlagEnabled } from '@/lib/posthog/flags'
import createNotebookFromMarkdown from '@/tools/notebooks/createFromMarkdown'
import type { Context } from '@/tools/types'

vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn(),
}))

const mockIsFeatureFlagEnabled = vi.mocked(isFeatureFlagEnabled)

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://app.posthog.com/project/${projectId}`,
        } as any,
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('42'),
            getAnalyticsContext: vi.fn().mockResolvedValue({ organizationId: 'org1', projectUuid: 'proj1' }),
        } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('notebooks-create-from-markdown', () => {
    beforeEach(() => {
        mockIsFeatureFlagEnabled.mockResolvedValue(true)
    })

    it('creates a notebook with executable analysis nodes from markdown', async () => {
        const requestMock = vi.fn().mockResolvedValueOnce({
            short_id: 'abc123',
            version: 0,
            title: 'Analysis',
        })
        const context = createMockContext(requestMock)
        const tool = createNotebookFromMarkdown()

        const result = await tool.handler(context, {
            title: 'Analysis',
            content:
                '# Analysis\n\n<hogql title="Recent events" return_variable="events_df">\nSELECT event, count() FROM events GROUP BY event\n</hogql>\n\n<python title="Summarize">\nprint(events_df.head())\n</python>',
        })

        expect(result._posthogUrl).toBe('https://app.posthog.com/project/42/notebooks/abc123')
        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/notebooks/',
            body: {
                title: 'Analysis',
                text_content:
                    'Analysis\n<hogql title="Recent events" return_variable="events_df">\nSELECT event, count() FROM events GROUP BY event\n</hogql>\n<python title="Summarize">\nprint(events_df.head())\n</python>',
                content: {
                    type: 'doc',
                    content: [
                        { type: 'heading', attrs: { level: 1 }, content: [{ type: 'text', text: 'Analysis' }] },
                        {
                            type: 'ph-hogql-sql',
                            attrs: {
                                code: 'SELECT event, count() FROM events GROUP BY event',
                                returnVariable: 'events_df',
                                title: 'Recent events',
                                __init: { showSettings: true },
                            },
                        },
                        {
                            type: 'ph-python',
                            attrs: {
                                code: 'print(events_df.head())',
                                title: 'Summarize',
                                __init: { showSettings: true },
                            },
                        },
                    ],
                },
            },
        })
    })

    it('rejects executable analysis nodes when the notebook-python flag is off', async () => {
        mockIsFeatureFlagEnabled.mockResolvedValue(false)
        const requestMock = vi.fn()
        const context = createMockContext(requestMock)
        const tool = createNotebookFromMarkdown()

        await expect(
            tool.handler(context, {
                title: 'Analysis',
                content: '<python>\nprint(1)\n</python>',
            })
        ).rejects.toThrow('notebook-python feature flag')
        expect(requestMock).not.toHaveBeenCalled()
    })

    it('creates old-style query nodes when the notebook-python flag is off', async () => {
        mockIsFeatureFlagEnabled.mockResolvedValue(false)
        const requestMock = vi.fn().mockResolvedValueOnce({
            short_id: 'abc123',
            version: 0,
            title: 'Analysis',
        })
        const context = createMockContext(requestMock)
        const tool = createNotebookFromMarkdown()

        await tool.handler(context, {
            title: 'Analysis',
            content: '<query title="SQL result">\n{"kind":"HogQLQuery","query":"SELECT 1"}\n</query>',
        })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/notebooks/',
            body: {
                title: 'Analysis',
                text_content: '<query title="SQL result">\n{"kind":"HogQLQuery","query":"SELECT 1"}\n</query>',
                content: {
                    type: 'doc',
                    content: [
                        {
                            type: 'ph-query',
                            attrs: {
                                title: 'SQL result',
                                query: { kind: 'HogQLQuery', query: 'SELECT 1' },
                            },
                        },
                    ],
                },
            },
        })
    })
})
