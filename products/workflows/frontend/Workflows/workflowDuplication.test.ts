import type { HogFlow } from './hogflows/types'
import { prepareWorkflowDuplicate } from './workflowDuplication'

describe('prepareWorkflowDuplicate', () => {
    it('removes server-owned identity and product ownership fields', () => {
        const workflow = {
            id: 'workflow-id',
            team_id: 1,
            name: 'Loop workflow',
            status: 'active',
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
            origin_product: 'loops',
            actions: [],
        } as unknown as HogFlow

        expect(prepareWorkflowDuplicate(workflow)).toEqual({
            name: 'Loop workflow (copy)',
            status: 'draft',
            actions: [],
        })
    })

    it.each([
        ['under the legacy ceiling', 10080, '7d'],
        ['above the legacy ceiling, clamped the way the worker clamps it', 259200, '90d'],
        ['a whole number of hours but not of days', 120, '2h'],
        ['not a whole number of hours', 100, '100m'],
    ])('respells a conversion window %s as a duration string', (_name, windowMinutes, expected) => {
        const workflow = {
            name: 'Legacy workflow',
            conversion: { window_minutes: windowMinutes, filters: [] },
        } as unknown as HogFlow

        expect(prepareWorkflowDuplicate(workflow).conversion).toEqual({ window: expected, filters: [] })
    })

    it.each([
        ['a window is already set', { window: '7d', window_minutes: 200000, filters: [] }],
        ['there is no usable window_minutes', { window_minutes: null, filters: [] }],
    ])('leaves the conversion alone when %s', (_name, conversion) => {
        const workflow = { name: 'Workflow', conversion } as unknown as HogFlow

        expect(prepareWorkflowDuplicate(workflow).conversion).toEqual(conversion)
    })
})
