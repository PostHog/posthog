import { describe, expect, it, vi } from 'vitest'

import { PostHogApiError, ToolInputValidationError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/warehouse_sources'
import externalDataSourcesDbSchema from '@/tools/posthogAiTools/externalDataSourcesDbSchema'
import externalDataSourcesJobs from '@/tools/posthogAiTools/externalDataSourcesJobs'
import externalDataSourcesPreview from '@/tools/posthogAiTools/externalDataSourcesPreview'
import externalDataSyncLogs, { normalizeLogMessage } from '@/tools/posthogAiTools/externalDataSyncLogs'
import type { Context } from '@/tools/types'

interface LogEntryFixture {
    log_source_id: string
    instance_id: string
    timestamp: string
    level: string
    message: string
}

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock, getProjectBaseUrl: () => 'https://app.example.com/project/42' } as any,
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
    const job = (createdAt: string, latestError: string | null = null): Record<string, unknown> => ({
        id: createdAt,
        created_at: createdAt,
        latest_error: latestError,
    })

    it('passes all query params as repeated keys when provided', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(
            context,
            tool.schema.parse({
                id: 'source-123',
                after: '2025-01-01T00:00:00Z',
                before: '2025-12-31T23:59:59Z',
                schemas: ['users', 'orders'],
                limit: 5,
            })
        )

        const path = requestMock.mock.calls[0]![0].path as string
        expect(path).toContain('/api/projects/42/external_data_sources/source-123/jobs/')
        expect(path).toContain('after=2025-01-01T00%3A00%3A00Z')
        expect(path).toContain('before=2025-12-31T23%3A59%3A59Z')
        expect(path).toContain('schemas=users')
        expect(path).toContain('schemas=orders')
        expect(path).toContain('limit=5')
        expect(requestMock.mock.calls[0]![0]).not.toHaveProperty('query')
    })

    it('sends only the default limit when no optional params are provided', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, tool.schema.parse({ id: 'source-456' }))

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/external_data_sources/source-456/jobs/?limit=20',
        })
    })

    it.each([
        ['comma-separated string', 'users, orders,', ['users', 'orders']],
        ['single string', 'users', ['users']],
        ['array', ['users', 'orders'], ['users', 'orders']],
        ['empty string', '', []],
    ])('accepts schemas as a %s', async (_name, schemas, expected) => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, tool.schema.parse({ id: 'source-1', schemas }))

        const searchParams = new URL(requestMock.mock.calls[0]![0].path as string, 'https://x.invalid').searchParams
        expect(searchParams.getAll('schemas')).toEqual(expected)
    })

    it.each([
        ['id', { id: 'source-1' }],
        ['source_id', { source_id: 'source-1' }],
        ['sourceId', { sourceId: 'source-1' }],
    ])('accepts the source id as %s', async (_name, input) => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, tool.schema.parse(input))

        expect(requestMock.mock.calls[0]![0].path).toContain('/external_data_sources/source-1/jobs/')
    })

    it.each([
        ['zero', 0],
        ['above max', 101],
        ['not a number', 'ten'],
        ['fraction', 2.5],
    ])('rejects a limit that is %s', (_name, limit) => {
        const tool = externalDataSourcesJobs()

        expect(tool.schema.safeParse({ id: 'source-1', limit }).success).toBe(false)
    })

    it('accepts a numeric string limit', () => {
        const tool = externalDataSourcesJobs()

        expect(tool.schema.parse({ id: 'source-1', limit: '7' })).toMatchObject({ limit: 7 })
    })

    it.each([
        ['full page', 2, [job('2025-01-03'), job('2025-01-02')], true, '2025-01-02'],
        ['short page', 3, [job('2025-01-03'), job('2025-01-02')], false, null],
        ['empty page', 3, [], false, null],
        ['page longer than limit from an older backend', 1, [job('2025-01-03'), job('2025-01-02')], true, '2025-01-03'],
    ])('pages with next_before on a %s', async (_name, limit, jobs, hasMore, nextBefore) => {
        const requestMock = vi.fn().mockResolvedValue(jobs)
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        const result = await tool.handler(context, tool.schema.parse({ id: 'source-1', limit }))

        expect(result.results).toHaveLength(Math.min(limit, jobs.length))
        expect(result.has_more).toBe(hasMore)
        expect(result.next_before).toBe(nextBefore)
    })

    it('truncates long job errors and keeps short ones', async () => {
        const requestMock = vi.fn().mockResolvedValue([job('2025-01-02', 'e'.repeat(2000)), job('2025-01-01', 'short')])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        const result = await tool.handler(context, tool.schema.parse({ id: 'source-1' }))

        expect(result.results[0]!.latest_error).toBe(`${'e'.repeat(500)}… [truncated, 2000 characters]`)
        expect(result.results[1]!.latest_error).toBe('short')
    })
})

describe('externalDataSyncLogs', () => {
    const SCHEMA_ID = '0190a1b2-c3d4-0e5f-8a9b-0c1d2e3f4a5b'
    const SOURCE_ID = '0190a1b2-c3d4-0e5f-8a9b-0c1d2e3f4a00'
    const OTHER_SCHEMA_ID = '0190a1b2-c3d4-0e5f-8a9b-0c1d2e3f4a11'

    const entry = (timestamp: string, message: string, level = 'ERROR', instanceId = 'run-1'): LogEntryFixture => ({
        log_source_id: SCHEMA_ID,
        instance_id: instanceId,
        timestamp,
        level,
        message,
    })

    const page = (
        results: LogEntryFixture[],
        count = results.length
    ): { count: number; results: LogEntryFixture[] } => ({
        count,
        results,
    })

    const notFound = (): PostHogApiError =>
        new PostHogApiError({ status: 404, statusText: 'Not Found', body: '{}', url: '/x', method: 'GET' })

    it.each([
        ['schema_id', { schema_id: SCHEMA_ID }],
        ['id', { id: SCHEMA_ID }],
        ['schemaId', { schemaId: SCHEMA_ID }],
    ])('accepts the table id as %s', async (_name, input) => {
        const requestMock = vi.fn().mockResolvedValue(page([]))
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        await tool.handler(context, tool.schema.parse(input))

        expect(requestMock.mock.calls[0]![0].path).toContain(
            `/api/projects/42/external_data_schemas/${SCHEMA_ID}/logs/`
        )
    })

    it.each([
        ['since only', { since: '2025-01-01T00:00:00Z' }, { after: '2025-01-01T00:00:00Z', before: null }],
        ['until only', { until: '2025-01-02T00:00:00Z' }, { after: null, before: '2025-01-02T00:00:00Z' }],
        [
            'both',
            { since: '2025-01-01T00:00:00Z', until: '2025-01-02T00:00:00Z' },
            { after: '2025-01-01T00:00:00Z', before: '2025-01-02T00:00:00Z' },
        ],
        ['neither', {}, { after: null, before: null }],
    ])('maps the time filter with %s', async (_name, input, expected) => {
        const requestMock = vi.fn().mockResolvedValue(page([]))
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        await tool.handler(context, tool.schema.parse({ schema_id: SCHEMA_ID, ...input }))

        const searchParams = new URL(requestMock.mock.calls[0]![0].path as string, 'https://x.invalid').searchParams
        expect(searchParams.get('after')).toBe(expected.after)
        expect(searchParams.get('before')).toBe(expected.before)
        expect(searchParams.get('level')).toBe('INFO,WARNING,ERROR')
        expect(searchParams.get('limit')).toBe('100')
    })

    it('groups repeated errors with count, first_seen and last_seen', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValue(
                page(
                    [
                        entry(
                            '2025-01-03T00:00:00Z',
                            'Connection to 10.0.0.12:5432 timed out after 30s',
                            'ERROR',
                            'run-3'
                        ),
                        entry('2025-01-02T12:00:00Z', 'Synced 1200 rows', 'INFO', 'run-2'),
                        entry(
                            '2025-01-02T00:00:00Z',
                            'Connection to 10.0.0.15:5432 timed out after 31s',
                            'ERROR',
                            'run-2'
                        ),
                        entry(
                            '2025-01-01T00:00:00Z',
                            'Connection to 10.0.0.12:5432 timed out after 30s',
                            'ERROR',
                            'run-1'
                        ),
                    ],
                    9
                )
            )
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        const result = await tool.handler(context, tool.schema.parse({ schema_id: SCHEMA_ID }))

        expect(result.total_matching).toBe(9)
        expect(result.entries_read).toBe(4)
        expect(result.has_more).toBe(true)
        expect(result.tables).toBeUndefined()
        expect(result.groups).toEqual([
            {
                level: 'ERROR',
                message: 'Connection to 10.0.0.12:5432 timed out after 30s',
                count: 3,
                first_seen: '2025-01-01T00:00:00Z',
                last_seen: '2025-01-03T00:00:00Z',
                job_ids: ['run-3', 'run-2', 'run-1'],
            },
            {
                level: 'INFO',
                message: 'Synced 1200 rows',
                count: 1,
                first_seen: '2025-01-02T12:00:00Z',
                last_seen: '2025-01-02T12:00:00Z',
                job_ids: ['run-2'],
            },
        ])
    })

    it('returns raw truncated entries when dedupe is false', async () => {
        const requestMock = vi
            .fn()
            .mockResolvedValue(
                page([entry('2025-01-02T00:00:00Z', 'x'.repeat(3000)), entry('2025-01-01T00:00:00Z', 'x'.repeat(3000))])
            )
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        const result = await tool.handler(context, tool.schema.parse({ schema_id: SCHEMA_ID, dedupe: false }))

        expect(result.groups).toBeUndefined()
        expect(result.entries).toHaveLength(2)
        expect(result.entries![0]!.message).toBe(`${'x'.repeat(1000)}… [truncated, 3000 characters]`)
        expect(result.has_more).toBe(false)
    })

    it('says so when the schema_id is a source id', async () => {
        const requestMock = vi.fn().mockRejectedValueOnce(notFound()).mockResolvedValueOnce({ id: SCHEMA_ID })
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        const error = await tool.handler(context, tool.schema.parse({ schema_id: SCHEMA_ID })).catch((e: unknown) => e)

        expect(error).toBeInstanceOf(ToolInputValidationError)
        expect((error as Error).message).toMatch(
            /is a data warehouse source id, not a table \(schema\) id.*source_id.*external-data-schemas-list/s
        )
        expect(requestMock.mock.calls[1]![0].path).toBe(
            `/api/projects/42/external_data_sources/${SCHEMA_ID}/?compact=true&include_schemas=false`
        )
    })

    it('rethrows the original 404 when the id is not a source id either', async () => {
        const original = notFound()
        const requestMock = vi.fn().mockRejectedValueOnce(original).mockRejectedValueOnce(notFound())
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        await expect(tool.handler(context, tool.schema.parse({ schema_id: SCHEMA_ID }))).rejects.toBe(original)
    })

    it('fans out over the failed and syncing tables of a source', async () => {
        const requestMock = vi.fn().mockImplementation(({ path }: { path: string }) => {
            if (path.startsWith(`/api/projects/42/external_data_sources/${SOURCE_ID}/`)) {
                return Promise.resolve({
                    schemas: [
                        { id: 'idle', name: 'idle', should_sync: false, latest_error: null },
                        { id: OTHER_SCHEMA_ID, name: 'orders', should_sync: true, latest_error: null },
                        { id: SCHEMA_ID, name: 'users', should_sync: false, latest_error: 'boom' },
                    ],
                })
            }
            if (path.includes(`/external_data_schemas/${SCHEMA_ID}/logs/`)) {
                return Promise.resolve(page([entry('2025-01-02T00:00:00Z', 'boom')]))
            }
            return Promise.resolve(page([entry('2025-01-03T00:00:00Z', 'boom')]))
        })
        const context = createMockContext(requestMock)
        const tool = externalDataSyncLogs()

        const result = await tool.handler(context, tool.schema.parse({ sourceId: SOURCE_ID }))

        expect(result.tables).toEqual([
            { id: SCHEMA_ID, name: 'users' },
            { id: OTHER_SCHEMA_ID, name: 'orders' },
        ])
        expect(result.groups!.map((group) => [group.table, group.count])).toEqual([
            ['orders', 1],
            ['users', 1],
        ])
        expect(requestMock.mock.calls.some(([call]) => call.path.includes('/external_data_schemas/idle/'))).toBe(false)
    })

    it('rejects a call with neither schema_id nor source_id', async () => {
        const tool = externalDataSyncLogs()

        await expect(tool.handler(createMockContext(vi.fn()), tool.schema.parse({ level: 'ERROR' }))).rejects.toThrow(
            ToolInputValidationError
        )
    })
})

describe('normalizeLogMessage', () => {
    it.each([
        ['numbers', 'timed out after 30s on port 5432', 'timed out after <n>s on port <n>'],
        ['uuids', 'job 0190a1b2-c3d4-0e5f-8a9b-0c1d2e3f4a5b failed', 'job <id> failed'],
        ['hex ids', 'request a1b2c3d4e5f6 failed', 'request <hex> failed'],
        ['words that look like hex', 'deadbeef facade', 'deadbeef facade'],
        ['whitespace', '  a \n b  ', 'a b'],
    ])('normalizes %s', (_name, message, expected) => {
        expect(normalizeLogMessage(message)).toBe(expected)
    })
})

describe('compact warehouse source reads', () => {
    it.each([
        ['external-data-sources-list', {}, '/api/projects/42/external_data_sources/'],
        ['external-data-sources-retrieve', { id: 'source-1' }, '/api/projects/42/external_data_sources/source-1/'],
        ['external-data-schemas-list', {}, '/api/projects/42/external_data_schemas/'],
    ])('%s asks for the compact form by default', async (name, input, path) => {
        const requestMock = vi.fn().mockResolvedValue({ results: [], schemas: [] })
        const tool = GENERATED_TOOLS[name]!()

        await tool.handler(createMockContext(requestMock), tool.schema.parse(input))

        expect(requestMock.mock.calls[0]![0]).toMatchObject({ path, query: { compact: true } })
    })

    it.each([
        ['external-data-sources-list', {}],
        ['external-data-sources-retrieve', { id: 'source-1' }],
        ['external-data-schemas-list', {}],
    ])('%s sends compact false when the caller asks for the full form', async (name, input) => {
        const requestMock = vi.fn().mockResolvedValue({ results: [], schemas: [] })
        const tool = GENERATED_TOOLS[name]!()

        await tool.handler(createMockContext(requestMock), tool.schema.parse({ ...input, compact: false }))

        expect(requestMock.mock.calls[0]![0].query).toMatchObject({ compact: false })
    })
})
