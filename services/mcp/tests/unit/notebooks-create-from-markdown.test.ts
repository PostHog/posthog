import { describe, expect, it, vi } from 'vitest'

import createNotebookFromMarkdown from '@/tools/notebooks/createFromMarkdown'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            request: requestMock,
            getProjectBaseUrl: (projectId: string) => `https://app.posthog.com/project/${projectId}`,
        } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('notebooks-create-from-markdown', () => {
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
})
