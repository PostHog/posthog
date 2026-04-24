import { describe, expect, it, vi } from 'vitest'

import queryIssueEvents from '@/tools/errorTracking/queryIssueEvents'
import type { Context } from '@/tools/types'

function createMockContext(runQueryMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            query: vi.fn().mockReturnValue({
                runQuery: runQueryMock,
            }),
            getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context
}

describe('query-error-tracking-issue-events', () => {
    const issueId = '00000000-0000-0000-0000-000000000000'

    it('builds a scoped EventsQuery and maps selected event properties', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            columns: [
                'uuid',
                'timestamp',
                'distinct_id',
                'properties.$exception_type',
                'properties.$exception_message',
                'properties.$exception_list',
                'properties.$current_url',
            ],
            results: [
                [
                    'event-uuid',
                    '2026-04-24T12:00:00Z',
                    'user-1',
                    'TypeError',
                    'Cannot read properties of undefined',
                    JSON.stringify([
                        {
                            type: 'TypeError',
                            value: 'Cannot read properties of undefined',
                            stacktrace: {
                                frames: [
                                    {
                                        filename: 'https://example.test/app.js',
                                        function: 'loadIssue',
                                        lineno: 42,
                                        colno: 9,
                                        in_app: true,
                                    },
                                ],
                            },
                            noisy_extra: 'drop me',
                        },
                    ]),
                    'https://example.test/app',
                ],
            ],
            hasMore: true,
            limit: 1,
            offset: 0,
        })
        const context = createMockContext(runQuery)
        const tool = queryIssueEvents()

        const filterGroup = [{ type: 'event' as const, key: '$browser', operator: 'exact' as const, value: ['Chrome'] }]
        const result = (await tool.handler(context, { issueId, searchQuery: "can't_load%_", filterGroup })) as any
        const query = runQuery.mock.calls[0]![0].query

        expect(query).toMatchObject({
            kind: 'EventsQuery',
            event: '$exception',
            filterTestAccounts: true,
            after: '-7d',
            orderBy: ['timestamp DESC'],
            limit: 1,
            offset: 0,
            tags: { productKey: 'error_tracking' },
        })
        expect(query.properties).toEqual(filterGroup)
        expect(query.select).toContain('properties.$exception_list')
        expect(query.where[0]).toContain(`issue_id = '${issueId}'`)
        expect(query.where[1]).toContain("can\\'t\\_load\\%\\_")
        expect(result).toEqual({
            results: [
                {
                    uuid: 'event-uuid',
                    timestamp: '2026-04-24T12:00:00Z',
                    distinct_id: 'user-1',
                    properties: {
                        $exception_type: 'TypeError',
                        $exception_message: 'Cannot read properties of undefined',
                        $exception_list: [
                            {
                                type: 'TypeError',
                                value: 'Cannot read properties of undefined',
                                stacktrace: {
                                    frames: [
                                        {
                                            filename: 'https://example.test/app.js',
                                            function: 'loadIssue',
                                            lineno: 42,
                                            colno: 9,
                                            in_app: true,
                                            source: 'https://example.test/app.js',
                                            mangled_name: 'loadIssue',
                                            line: 42,
                                            column: 9,
                                        },
                                    ],
                                },
                            },
                        ],
                        $current_url: 'https://example.test/app',
                    },
                },
            ],
            hasMore: true,
            limit: 1,
            offset: 0,
            nextOffset: 1,
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
    })

    it('caps limit at twenty through schema validation', async () => {
        const context = createMockContext(vi.fn())
        const tool = queryIssueEvents()

        await expect(tool.handler(context, { issueId, limit: 21 })).rejects.toThrow()
    })
})
