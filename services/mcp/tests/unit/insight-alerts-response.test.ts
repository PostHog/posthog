import { describe, expect, it, vi } from 'vitest'

import { getToolByName } from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'
import type { Context } from '@/tools/types'

const user = { id: 1, uuid: 'user-uuid', first_name: 'Test', email: 'test@example.com' }

const alert = {
    id: 'alert-uuid',
    name: 'Signups dropped',
    state: 'Not firing',
    enabled: true,
    threshold: { configuration: { type: 'absolute', bounds: { lower: 10 } } },
    created_by: user,
    subscribed_users: [user],
    checks: [{ id: 'check-uuid', state: 'Not firing' }],
    insight: { id: 7, short_id: 'AbCd1234', query: { kind: 'InsightVizNode' }, dashboards: [3], created_by: user },
}

const insight = {
    id: 7,
    short_id: 'AbCd1234',
    name: 'Signups',
    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery' } },
    created_by: user,
    alerts: [alert],
}

function createContext(response: unknown): Context {
    return {
        api: {
            request: vi.fn().mockResolvedValue(response),
            getProjectBaseUrl: vi.fn().mockReturnValue('https://app.example.com/project/17'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('17'),
        },
    } as unknown as Context
}

describe('insight tools alert projection', () => {
    it('insights-list returns only an alert summary per insight', async () => {
        const tool = getToolByName(GENERATED_TOOLS, 'insights-list')
        const context = createContext({ count: 1, next: null, previous: null, results: [insight] })

        const result = (await tool.handler(context, {})) as { results: Record<string, unknown>[] }

        expect(result.results[0]!.alerts).toEqual([
            { id: 'alert-uuid', name: 'Signups dropped', state: 'Not firing', enabled: true },
        ])
    })

    it.each([['insight-get'], ['insight-update']])(
        '%s drops the nested insight and people from alerts',
        async (name) => {
            const tool = getToolByName(GENERATED_TOOLS, name)
            const context = createContext(insight)

            const result = (await tool.handler(context, { id: 7 })) as Record<string, unknown>

            expect(result.query).toEqual(insight.query)
            expect(result.alerts).toEqual([
                {
                    id: 'alert-uuid',
                    name: 'Signups dropped',
                    state: 'Not firing',
                    enabled: true,
                    threshold: alert.threshold,
                },
            ])
        }
    )
})
