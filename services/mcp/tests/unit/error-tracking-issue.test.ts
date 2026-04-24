import { describe, expect, it, vi } from 'vitest'

import queryIssue from '@/tools/errorTracking/queryIssue'
import { POSTHOG_META_KEY, type Context } from '@/tools/types'

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

describe('query-error-tracking-issue', () => {
    const issueId = '00000000-0000-0000-0000-000000000000'

    it('builds a compact single-issue ErrorTrackingQuery', async () => {
        const runQuery = vi
            .fn()
            .mockResolvedValueOnce({
                results: [
                    {
                        id: issueId,
                        name: 'TypeError',
                        status: 'active',
                        source: 'fallback.js',
                        function: 'fallbackFunction',
                        aggregations: { occurrences: 3, users: 2, sessions: 1 },
                        first_event: { properties: { huge: true } },
                    },
                ],
            })
            .mockResolvedValueOnce({
                columns: ['properties.$exception_list', 'properties.$exception_releases'],
                results: [
                    [
                        JSON.stringify([
                            {
                                stacktrace: {
                                    frames: [
                                        {
                                            source: 'outer.js',
                                            function: 'outer',
                                            line: 1,
                                            column: 2,
                                            in_app: false,
                                        },
                                        {
                                            source: 'app.js',
                                            function: 'loadIssue',
                                            line: 42,
                                            column: 9,
                                            in_app: true,
                                        },
                                    ],
                                },
                            },
                        ]),
                        JSON.stringify({
                            release_a: {
                                version: '2026.04.24',
                                project: 'web',
                                timestamp: '2026-04-24T12:00:00Z',
                                metadata: { git: { commit_id: 'abc123', branch: 'main', repo_name: 'posthog' } },
                            },
                        }),
                    ],
                ],
            })
        const context = createMockContext(runQuery)
        const tool = queryIssue()

        const result = (await tool.handler(context, { issueId })) as any
        const query = runQuery.mock.calls[0]![0].query
        const contextEventQuery = runQuery.mock.calls[1]![0].query

        expect(query).toMatchObject({
            kind: 'ErrorTrackingQuery',
            issueId,
            dateRange: { date_from: '-7d' },
            filterTestAccounts: true,
            volumeResolution: 0,
            limit: 1,
            orderBy: 'last_seen',
            orderDirection: 'DESC',
            withAggregations: true,
            withFirstEvent: false,
            withLastEvent: false,
            tags: { productKey: 'error_tracking' },
        })
        expect(contextEventQuery).toMatchObject({
            kind: 'EventsQuery',
            event: '$exception',
            select: ['properties.$exception_list', 'properties.$exception_releases'],
            filterTestAccounts: true,
            after: '-7d',
            orderBy: ['timestamp DESC'],
            limit: 1,
            tags: { productKey: 'error_tracking' },
        })
        expect(contextEventQuery.where[0]).toContain(`issue_id = '${issueId}'`)
        expect(result).toEqual({
            id: issueId,
            name: 'TypeError',
            status: 'active',
            source: 'fallback.js',
            function: 'fallbackFunction',
            aggregations: { occurrences: 3, users: 2, sessions: 1 },
            top_in_app_frame: {
                function: 'loadIssue',
                source: 'app.js',
                line: 42,
                column: 9,
                in_app: true,
            },
            latest_release: {
                version: '2026.04.24',
                project: 'web',
                timestamp: '2026-04-24T12:00:00Z',
                commit_id: 'abc123',
                branch: 'main',
                repo_name: 'posthog',
            },
            impact: { occurrences: 3, users: 2, sessions: 1 },
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
        expect(tool._meta?.[POSTHOG_META_KEY]?.outputFormat).toBe('json')
    })

    it('includes a compact sparkline only when requested', async () => {
        const runQuery = vi
            .fn()
            .mockResolvedValueOnce({
                results: [
                    {
                        id: issueId,
                        name: 'TypeError',
                        aggregations: {
                            occurrences: 3,
                            users: 2,
                            sessions: 1,
                            volumeRange: [0, 1, 2],
                        },
                    },
                ],
            })
            .mockResolvedValueOnce({ results: [] })
        const context = createMockContext(runQuery)
        const tool = queryIssue()

        const result = (await tool.handler(context, { issueId, includeSparkline: true, volumeResolution: 3 })) as any

        expect(runQuery.mock.calls[0]![0].query.volumeResolution).toBe(3)
        expect(result.sparkline).toEqual([0, 1, 2])
    })

    it('returns null result when the issue is not found', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [] })
        const context = createMockContext(runQuery)
        const tool = queryIssue()

        const result = await tool.handler(context, { issueId })

        expect(result).toEqual({
            result: null,
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
        expect(runQuery).toHaveBeenCalledOnce()
    })
})
