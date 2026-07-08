import { describe, expect, it, vi } from 'vitest'

import externalDataSourcesDbSchema from '@/tools/posthogAiTools/externalDataSourcesDbSchema'
import externalDataSourcesJobs from '@/tools/posthogAiTools/externalDataSourcesJobs'
import externalDataSourcesPreview from '@/tools/posthogAiTools/externalDataSourcesPreview'
import {
    suggestErrorTrackingFilters,
    suggestRevenueAnalyticsFilters,
    suggestSessionRecordingFilters,
    suggestWebAnalyticsFilters,
} from '@/tools/posthogAiTools/suggestFilterTools'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
        trackEvent: async () => {},
    }
}

describe('externalDataSourcesDbSchema', () => {
    it('spreads payload into flat body alongside source_type', async () => {
        const requestMock = vi.fn().mockResolvedValue({ tables: [] })
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesDbSchema()

        await tool.handler(context, {
            source_type: 'Postgres',
            payload: {
                host: 'localhost',
                port: '5432',
                database: 'mydb',
                user: 'admin',
                password: 'secret',
                schema: 'public',
            },
        })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/external_data_sources/database_schema/',
            body: {
                source_type: 'Postgres',
                host: 'localhost',
                port: '5432',
                database: 'mydb',
                user: 'admin',
                password: 'secret',
                schema: 'public',
            },
        })
    })

    it('does not nest payload as a sub-object', async () => {
        const requestMock = vi.fn().mockResolvedValue({})
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesDbSchema()

        await tool.handler(context, {
            source_type: 'MySQL',
            payload: { host: 'db.example.com' },
        })

        const body = requestMock.mock.calls[0]![0].body
        expect(body).not.toHaveProperty('payload')
        expect(body.host).toBe('db.example.com')
        expect(body.source_type).toBe('MySQL')
    })
})

describe('externalDataSourcesPreview', () => {
    it('posts a nested payload alongside source_type, resource_name and limit', async () => {
        const requestMock = vi.fn().mockResolvedValue({ rows: [], row_count: 0, columns: [], error: null })
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesPreview()

        await tool.handler(context, {
            source_type: 'Custom',
            payload: { manifest_json: '{"client":{}}', auth_api_key: 'sk_test' },
            resource_name: 'users',
            limit: 5,
        })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'POST',
            path: '/api/projects/42/external_data_sources/preview_resource/',
            body: {
                source_type: 'Custom',
                payload: { manifest_json: '{"client":{}}', auth_api_key: 'sk_test' },
                resource_name: 'users',
                limit: 5,
            },
        })
    })

    it('keeps credentials nested inside payload, not at the top level', async () => {
        const requestMock = vi.fn().mockResolvedValue({})
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesPreview()

        await tool.handler(context, {
            source_type: 'Custom',
            payload: { manifest_json: '{}', auth_token: 'secret' },
            resource_name: 'users',
        })

        const body = requestMock.mock.calls[0]![0].body
        expect(body).not.toHaveProperty('auth_token')
        expect(body.payload.auth_token).toBe('secret')
    })
})

describe('externalDataSourcesJobs', () => {
    it('passes all query params as repeated keys when provided', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, {
            id: 'source-123',
            after: '2025-01-01T00:00:00Z',
            before: '2025-12-31T23:59:59Z',
            schemas: ['users', 'orders'],
        })

        const path = requestMock.mock.calls[0]![0].path as string
        expect(path).toContain('/api/projects/42/external_data_sources/source-123/jobs/')
        expect(path).toContain('after=2025-01-01T00%3A00%3A00Z')
        expect(path).toContain('before=2025-12-31T23%3A59%3A59Z')
        expect(path).toContain('schemas=users')
        expect(path).toContain('schemas=orders')
        expect(requestMock.mock.calls[0]![0]).not.toHaveProperty('query')
    })

    it('omits query string when no optional params provided', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, { id: 'source-456' })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/external_data_sources/source-456/jobs/',
        })
    })

    it('includes only provided optional params in query string', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, {
            id: 'source-789',
            after: '2025-06-01T00:00:00Z',
        })

        const path = requestMock.mock.calls[0]![0].path as string
        expect(path).toContain('after=2025-06-01T00%3A00%3A00Z')
        expect(path).not.toContain('before=')
        expect(path).not.toContain('schemas=')
    })
})

describe('suggest-*-filters echo tools', () => {
    const context = createMockContext(vi.fn())

    // Each payload mirrors what the legacy langgraph filter tools produced for that scene. The suite
    // guards two regressions: a schema tightened past the loose floor (rejecting a valid legacy filter
    // payload, silently breaking the browser apply-back) and a handler that stops echoing the input.
    const cases: Array<[string, () => any, Record<string, unknown>]> = [
        [
            'suggest-web-analytics-filters',
            suggestWebAnalyticsFilters,
            {
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
                date_from: '-7d',
                date_to: null,
                doPathCleaning: true,
                compareFilter: { compare: true },
            },
        ],
        [
            'suggest-revenue-analytics-filters',
            suggestRevenueAnalyticsFilters,
            {
                properties: [{ key: 'product', value: ['A'], type: 'revenue_analytics' }],
                breakdown: [{ property: 'country', type: 'revenue_analytics' }],
                date_from: '-30d',
                date_to: null,
            },
        ],
        [
            'suggest-error-tracking-filters',
            suggestErrorTrackingFilters,
            {
                newFilters: [{ key: 'level', value: ['error'], operator: 'exact', type: 'event' }],
                removedFilterIndexes: [0],
                dateRange: { date_from: '-24h', date_to: null },
                filterTestAccounts: true,
                orderBy: 'last_seen',
                orderDirection: 'DESC',
                status: 'active',
                searchQuery: 'timeout',
            },
        ],
        [
            'suggest-session-recording-filters',
            suggestSessionRecordingFilters,
            {
                recordings_filters: {
                    duration: [{ key: 'duration', value: 60, operator: 'gt', type: 'recording' }],
                    filter_group: { type: 'AND', values: [] },
                    date_from: '-24h',
                    date_to: null,
                    filter_test_accounts: true,
                    order: 'start_time',
                    order_direction: 'DESC',
                },
            },
        ],
    ]

    it.each(cases)('%s validates a legacy filter payload and echoes it back', async (name, factory, payload) => {
        const tool = factory()
        expect(tool.name).toBe(name)

        const parsed = tool.schema.safeParse(payload)
        expect(parsed.success).toBe(true)
        if (!parsed.success) {
            return
        }

        const result = await tool.handler(context, parsed.data)
        expect(result.filters).toEqual(payload)
        expect(result.status).toBe('sent_to_open_page')
    })

    it('keeps the schema floor: rejects a web analytics payload whose properties is not an array', () => {
        expect(suggestWebAnalyticsFilters().schema.safeParse({ properties: 'not-an-array' }).success).toBe(false)
    })
})
