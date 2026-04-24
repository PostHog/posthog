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

        expect(runQuery.mock.calls[0]![0].query).toMatchObject({
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

        await tool.handler(context, {
            library: ['posthog-js', 'posthog-node'],
            release: '2026.04.24',
            environment: 'production',
            fingerprint: 'fingerprint-1',
            user: 'alice@example.com',
            personId: 'person-uuid',
            url: '/checkout',
            filePath: 'src/components/Checkout Button.tsx',
            filterGroup: [{ type: 'event', key: '$browser', operator: 'exact', value: ['Chrome'] }],
        })

        const query = runQuery.mock.calls[0]![0].query

        expect(query.personId).toBe('person-uuid')
        expect(query.searchQuery).toBe('alice@example.com "src/components/Checkout Button.tsx"')
        expect(query.filterGroup).toEqual(
            expect.arrayContaining([
                { type: 'event', key: '$browser', operator: 'exact', value: ['Chrome'] },
                { type: 'event', key: '$lib', operator: 'exact', value: ['posthog-js', 'posthog-node'] },
                { type: 'event', key: '$exception_releases', operator: 'icontains', value: '2026.04.24' },
                { type: 'event', key: '$environment', operator: 'exact', value: ['production'] },
                { type: 'event', key: '$exception_fingerprint', operator: 'exact', value: ['fingerprint-1'] },
                { type: 'event', key: '$current_url', operator: 'icontains', value: '/checkout' },
            ])
        )
    })
})
