import { describe, expect, it, vi } from 'vitest'

import { queryHandler } from '@/tools/insights/query'
import type { Context } from '@/tools/types'

const filtersOverrideObject = { date_from: '-7d' }
const variablesOverrideObject = {
    '019d4838-1da4-0000-33c7-2561bf01f1c9': {
        code_name: 'eventname',
        variableId: '019d4838-1da4-0000-33c7-2561bf01f1c9',
        value: 'signed_up',
    },
}

interface InsightsCallArgs {
    insightId: string
    variables_override?: string
    filters_override?: string
}

interface MockHandles {
    context: Context
    insightsGet: ReturnType<typeof vi.fn>
    insightsQuery: ReturnType<typeof vi.fn>
}

function createContext(): MockHandles {
    const insightsGet = vi.fn().mockResolvedValue({
        success: true,
        data: {
            id: 42,
            short_id: 'abc12345',
            query: { kind: 'HogQLQuery', query: 'select 1' },
        },
    })
    const insightsQuery = vi.fn().mockResolvedValue({
        success: true,
        data: { columns: ['c'], results: [[1]] },
    })
    const context = {
        api: {
            insights: vi.fn().mockReturnValue({
                get: insightsGet,
                query: insightsQuery,
            }),
            request: vi.fn(),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrgID: vi.fn(),
            getRegion: vi.fn().mockResolvedValue('us'),
        },
        env: { POSTHOG_BASE_URL: 'https://us.posthog.com' },
        sessionManager: {},
        cache: {},
        getDistinctId: async () => 'test',
    } as unknown as Context

    return { context, insightsGet, insightsQuery }
}

describe('queryHandler — overrides forwarding', () => {
    it('forwards a string variables_override unchanged', async () => {
        const { context, insightsGet } = createContext()
        const variables_override = JSON.stringify(variablesOverrideObject)

        await queryHandler(context, { insightId: '42', output_format: 'json', variables_override })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(variables_override)
        expect(call.filters_override).toBeUndefined()
    })

    it('JSON.stringify-s an object variables_override before forwarding', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            // Cast through unknown — at runtime this is what an LLM sends; the
            // tool schema accepts it, but the inner client typing is string-only.
            variables_override: variablesOverrideObject as unknown as string,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(JSON.stringify(variablesOverrideObject))
    })

    it('JSON.stringify-s an object filters_override before forwarding', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            filters_override: filtersOverrideObject as unknown as string,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.filters_override).toBe(JSON.stringify(filtersOverrideObject))
    })

    it('handles undefined overrides without coercing them to "undefined"', async () => {
        const { context, insightsGet } = createContext()

        await queryHandler(context, { insightId: '42', output_format: 'json' })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBeUndefined()
        expect(call.filters_override).toBeUndefined()
    })

    it('forwards mixed string + object overrides correctly', async () => {
        const { context, insightsGet } = createContext()
        const filters_override = JSON.stringify(filtersOverrideObject)

        await queryHandler(context, {
            insightId: '42',
            output_format: 'json',
            variables_override: variablesOverrideObject as unknown as string,
            filters_override,
        })

        const call = insightsGet.mock.calls[0]![0] as InsightsCallArgs
        expect(call.variables_override).toBe(JSON.stringify(variablesOverrideObject))
        expect(call.filters_override).toBe(filters_override)
    })
})
