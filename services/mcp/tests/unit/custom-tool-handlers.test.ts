import { describe, expect, it, vi } from 'vitest'

import externalDataSourcesJobs from '@/tools/posthogAiTools/externalDataSourcesJobs'
import type { Context } from '@/tools/types'

function createMockContext(requestMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: { request: requestMock } as any,
        stateManager: { getProjectId: vi.fn().mockResolvedValue('42') } as any,
        env: {} as any,
        sessionManager: {} as any,
        cache: {} as any,
        getDistinctId: async () => 'test-distinct-id',
    }
}

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
