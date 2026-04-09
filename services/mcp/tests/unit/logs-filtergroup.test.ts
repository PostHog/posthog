import { describe, expect, it, vi } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/logs'
import type { Context } from '@/tools/types'

function createMockContext(): { context: Context; getRequestBody: () => Record<string, unknown> | undefined } {
    let capturedBody: Record<string, unknown> | undefined
    const context = {
        api: {
            request: vi.fn().mockImplementation(async (opts: { body?: Record<string, unknown> }) => {
                capturedBody = opts.body
                return { results: [] }
            }),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('2'),
        },
    } as unknown as Context
    return { context, getRequestBody: () => capturedBody }
}

describe('query-logs filterGroup wrapping', () => {
    it('wraps flat filterGroup array into PropertyGroupFilter dict', async () => {
        const tool = GENERATED_TOOLS['query-logs']()
        const { context, getRequestBody } = createMockContext()

        await tool.handler(context, {
            query: {
                dateRange: { date_from: '-1h' },
                filterGroup: [{ key: 'message', operator: 'icontains', type: 'log', value: 'bearer_auth' }],
            },
        })

        const body = getRequestBody()
        const query = body?.query as Record<string, unknown>
        expect(query.filterGroup).toEqual({
            type: 'AND',
            values: [{ type: 'AND', values: [{ key: 'message', operator: 'icontains', type: 'log', value: 'bearer_auth' }] }],
        })
    })

    it('removes empty filterGroup array', async () => {
        const tool = GENERATED_TOOLS['query-logs']()
        const { context, getRequestBody } = createMockContext()

        await tool.handler(context, {
            query: {
                dateRange: { date_from: '-1h' },
                filterGroup: [],
            },
        })

        const body = getRequestBody()
        const query = body?.query as Record<string, unknown>
        expect(query.filterGroup).toBeUndefined()
    })

    it('passes through when no filterGroup is provided', async () => {
        const tool = GENERATED_TOOLS['query-logs']()
        const { context, getRequestBody } = createMockContext()

        await tool.handler(context, {
            query: {
                dateRange: { date_from: '-1h' },
            },
        })

        const body = getRequestBody()
        const query = body?.query as Record<string, unknown>
        expect(query.filterGroup).toBeUndefined()
    })
})
