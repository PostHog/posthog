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

    it('sends no filterGroup when default empty array is used', async () => {
        const tool = GENERATED_TOOLS['query-logs']()
        const { context, getRequestBody } = createMockContext()

        await tool.handler(context, {
            query: {
                dateRange: { date_from: '-1h' },
                filterGroup: [], // this is the default
            },
        })

        const body = getRequestBody()
        const query = body?.query as Record<string, unknown>
        // Empty array should be removed, not sent as []
        expect(query.filterGroup).toBeUndefined()
    })

    it('would have sent raw array without the fix (regression check)', async () => {
        // Simulates the old broken behavior to document what was wrong
        const filters = [{ key: 'message', operator: 'icontains', type: 'log', value: 'test' }]
        // Old code: body['query'] = params.query (passes array as-is)
        const oldPayload = { filterGroup: filters }
        // Backend expects a dict, not an array
        expect(Array.isArray(oldPayload.filterGroup)).toBe(true) // this is what broke it

        // New code wraps it
        const tool = GENERATED_TOOLS['query-logs']()
        const { context, getRequestBody } = createMockContext()
        await tool.handler(context, { query: { filterGroup: filters } })
        const query = getRequestBody()?.query as Record<string, unknown>
        // Fixed: now a dict, not an array
        expect(Array.isArray(query.filterGroup)).toBe(false)
        expect(query.filterGroup).toHaveProperty('type', 'AND')
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
