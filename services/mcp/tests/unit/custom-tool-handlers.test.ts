import { describe, expect, it, vi } from 'vitest'

import externalDataSourcesDbSchema from '@/tools/posthogAiTools/externalDataSourcesDbSchema'
import externalDataSourcesJobs from '@/tools/posthogAiTools/externalDataSourcesJobs'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
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

describe('externalDataSourcesJobs', () => {
    it('passes all query params when provided', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, {
            id: 'source-123',
            after: '2025-01-01T00:00:00Z',
            before: '2025-12-31T23:59:59Z',
            schemas: ['users', 'orders'],
        })

        expect(requestMock).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/42/external_data_sources/source-123/jobs/',
            query: {
                after: '2025-01-01T00:00:00Z',
                before: '2025-12-31T23:59:59Z',
                schemas: ['users', 'orders'],
            },
        })
    })

    it('omits undefined optional params from query', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, { id: 'source-456' })

        const query = requestMock.mock.calls[0]![0].query
        expect(query).toEqual({})
        expect(query).not.toHaveProperty('after')
        expect(query).not.toHaveProperty('before')
        expect(query).not.toHaveProperty('schemas')
    })

    it('includes only provided optional params', async () => {
        const requestMock = vi.fn().mockResolvedValue([])
        const context = createMockContext(requestMock)
        const tool = externalDataSourcesJobs()

        await tool.handler(context, {
            id: 'source-789',
            after: '2025-06-01T00:00:00Z',
        })

        const query = requestMock.mock.calls[0]![0].query
        expect(query).toEqual({ after: '2025-06-01T00:00:00Z' })
    })
})
