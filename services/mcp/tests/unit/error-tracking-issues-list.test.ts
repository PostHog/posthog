import { describe, expect, it, vi } from 'vitest'

import queryIssuesList from '@/tools/errorTracking/queryIssuesList'
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

describe('query-error-tracking-issues-list', () => {
    it('builds a compact tagged ErrorTrackingQuery with defaults', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            results: [
                {
                    id: 'issue-1',
                    name: 'TypeError',
                    status: 'active',
                    first_event: { properties: { huge: true } },
                    aggregations: { occurrences: 3 },
                },
            ],
            hasMore: true,
            limit: 25,
            offset: 0,
        })
        const context = createMockContext(runQuery)
        const tool = queryIssuesList()

        const result = (await tool.handler(context, {})) as any

        const query = runQuery.mock.calls[0]![0].query
        expect(query).toMatchObject({
            kind: 'ErrorTrackingQuery',
            dateRange: { date_from: '-7d' },
            status: 'active',
            orderBy: 'occurrences',
            orderDirection: 'DESC',
            limit: 25,
            volumeResolution: 0,
            filterTestAccounts: true,
            tags: { productKey: 'error_tracking' },
            withAggregations: true,
            withFirstEvent: false,
            withLastEvent: false,
        })
        expect(query).not.toHaveProperty('filterGroup')
        expect(result).toEqual({
            results: [
                {
                    id: 'issue-1',
                    name: 'TypeError',
                    status: 'active',
                    aggregations: { occurrences: 3 },
                },
            ],
            hasMore: true,
            limit: 25,
            offset: 0,
            nextOffset: 25,
            _posthogUrl: 'http://localhost:8010/project/1/error_tracking',
        })
    })

    it('maps friendly fields into backend filters', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [] })
        const context = createMockContext(runQuery)
        const tool = queryIssuesList()
        const fingerprint =
            '012a0ac2ab9ad1a858f753798c0e7d92ed2075bd861416a93faf4414021079af18873b1e07729870c94fe3fd4b789a29118772ce39eab9a7637e5d181d7fbc8e'

        await tool.handler(context, {
            library: ['posthog-js', 'posthog-node'],
            release: "2026.04.24'\\release",
            fingerprint,
            user: 'alice@example.com',
            personId: 'person-uuid',
            url: '/checkout',
            filePath: 'src/components/Checkout Button.tsx',
            filterGroup: [{ type: 'event', key: '$browser', operator: 'exact', value: ['Chrome'] }],
        })

        const query = runQuery.mock.calls[0]![0].query

        expect(query.personId).toBe('person-uuid')
        expect(query.searchQuery).toBe('alice@example.com "src/components/Checkout Button.tsx"')
        expect(query.filterGroup).toEqual({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: expect.arrayContaining([
                        { type: 'event', key: '$browser', operator: 'exact', value: ['Chrome'] },
                        { type: 'event', key: '$lib', operator: 'exact', value: ['posthog-js', 'posthog-node'] },
                        {
                            type: 'hogql',
                            key: "arrayExists(r -> (r.1 = '2026.04.24\\'\\\\release' OR JSONExtractString(r.2, 'version') = '2026.04.24\\'\\\\release' OR JSONExtractString(JSONExtractRaw(r.2, 'metadata'), 'git', 'commit_id') = '2026.04.24\\'\\\\release'), JSONExtractKeysAndValuesRaw(ifNull(nullIf(JSONExtractRaw(properties, '$exception_releases'), ''), '{}')))",
                        },
                        { type: 'event', key: '$exception_fingerprint', operator: 'exact', value: [fingerprint] },
                        { type: 'event', key: '$current_url', operator: 'icontains', value: '/checkout' },
                    ]),
                },
            ],
        })
        expect(query.filterGroup.values[0].values).toHaveLength(5)
    })

    it('trims limit-plus-one backend pages to the requested limit', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            results: [{ id: 'issue-1' }, { id: 'issue-2' }, { id: 'issue-3' }],
            offset: 0,
        })
        const context = createMockContext(runQuery)
        const tool = queryIssuesList()

        const result = (await tool.handler(context, { limit: 2 })) as any

        expect(result.results).toEqual([{ id: 'issue-1' }, { id: 'issue-2' }])
        expect(result.hasMore).toBe(true)
        expect(result.limit).toBe(2)
        expect(result.nextOffset).toBe(2)
    })
})
