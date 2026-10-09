import { describe, expect, it, vi } from 'vitest'

import viewGetHooks from '@/tools/dataWarehouse/viewGetHooks'
import type { Context } from '@/tools/types'

const VIEW = { id: 'view-1', name: 'orders' }
const SUGGESTION = {
    id: 'suggestion-1',
    kind: 'materialize',
    subject_kind: 'saved_query',
    subject_id: 'view-1',
    payload: { subject_name: 'orders' },
    status: 'proposed',
    score: 3,
    can_act: true,
}

function contextWith(request: () => Promise<unknown>): { context: Context; request: ReturnType<typeof vi.fn> } {
    const requestMock = vi.fn(request)
    const context = {
        stateManager: { getProjectId: async () => '7' },
        api: { request: requestMock },
    } as unknown as Context
    return { context, request: requestMock }
}

describe('viewGetHooks.afterResponse', () => {
    it('attaches the open suggestions of the view', async () => {
        const { context, request } = contextWith(async () => ({ count: 1, results: [SUGGESTION] }))

        const result = await viewGetHooks.afterResponse(context, { id: VIEW.id }, VIEW)

        expect(request).toHaveBeenCalledWith({
            method: 'GET',
            path: '/api/projects/7/warehouse_suggestions/',
            query: { subject_id: VIEW.id, status: 'proposed' },
        })
        expect(result).toEqual({
            ...VIEW,
            open_suggestions: [
                { id: 'suggestion-1', kind: 'materialize', payload: { subject_name: 'orders' }, can_act: true },
            ],
            open_suggestions_note: expect.stringContaining('warehouse-suggestions-accept'),
        })
    })

    it.each([
        { name: 'no open suggestions', request: async () => ({ count: 0, results: [] }) },
        {
            name: 'the suggestions request fails',
            request: async () => {
                throw new Error('Warehouse suggestions are not enabled for this project.')
            },
        },
    ])('returns the view unchanged when $name', async ({ request }) => {
        const { context } = contextWith(request)

        await expect(viewGetHooks.afterResponse(context, { id: VIEW.id }, VIEW)).resolves.toBe(VIEW)
    })
})
