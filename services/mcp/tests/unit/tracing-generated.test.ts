import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/tracing'
import type { Context } from '@/tools/types'

type SpansPage = { results: unknown[]; hasMore: boolean; nextCursor: string | null }

const span = (spanId: string): Record<string, unknown> => ({
    uuid: `uuid-${spanId}`,
    trace_id: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    span_id: spanId,
    name: 'GET /api',
    timestamp: '2026-01-01T00:00:00Z',
})

describe('query-apm-spans', () => {
    it('returns the continuation cursor so the agent can request the next page', async () => {
        const request = vi
            .fn()
            .mockResolvedValueOnce({ results: [span('0000000000000001')], hasMore: true, nextCursor: 'cursor-1' })
            .mockResolvedValueOnce({ results: [span('0000000000000002')], hasMore: false, nextCursor: null })
        const context = {
            api: { request },
            stateManager: { getProjectId: async () => '42' },
        } as unknown as Context
        const tool = GENERATED_TOOLS['query-apm-spans']!()

        const firstPage = (await tool.handler(
            context,
            tool.schema.parse({ query: { flatSpans: true, statusCodes: [2], limit: 1 } })
        )) as SpansPage
        expect(firstPage).toMatchObject({ hasMore: true, nextCursor: 'cursor-1' })

        const secondPage = (await tool.handler(
            context,
            tool.schema.parse({ query: { flatSpans: true, statusCodes: [2], limit: 1, after: firstPage.nextCursor } })
        )) as SpansPage
        expect(request).toHaveBeenLastCalledWith(
            expect.objectContaining({ body: { query: expect.objectContaining({ after: 'cursor-1' }) } })
        )
        expect(secondPage).toMatchObject({ hasMore: false, nextCursor: null })
        expect(secondPage.results).not.toEqual(firstPage.results)
    })
})
