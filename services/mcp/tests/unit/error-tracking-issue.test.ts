import { describe, expect, it, vi } from 'vitest'

import queryIssue from '@/tools/errorTracking/queryIssue'
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

describe('query-error-tracking-issue', () => {
    const issueId = '00000000-0000-0000-0000-000000000000'

    it('builds a compact single-issue ErrorTrackingQuery', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            results: [
                {
                    id: issueId,
                    name: 'TypeError',
                    status: 'active',
                    aggregations: { occurrences: 3 },
                    first_event: { properties: { huge: true } },
                },
            ],
        })
        const context = createMockContext(runQuery)
        const tool = queryIssue()

        const result = (await tool.handler(context, { issueId })) as any
        const query = runQuery.mock.calls[0]![0].query

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
        expect(result).toEqual({
            id: issueId,
            name: 'TypeError',
            status: 'active',
            aggregations: { occurrences: 3 },
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
    })

    it('returns null result when the issue is not found', async () => {
        const context = createMockContext(vi.fn().mockResolvedValue({ results: [] }))
        const tool = queryIssue()

        const result = await tool.handler(context, { issueId })

        expect(result).toEqual({
            result: null,
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
    })
})
