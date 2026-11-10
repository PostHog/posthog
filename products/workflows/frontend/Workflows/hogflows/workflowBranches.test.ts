import type { HogFlowAction, HogFlowEdge } from './types'
import { getWorkflowBranchLabel } from './workflowBranches'

const edge = (from: string, to: string, type: HogFlowEdge['type'] = 'continue', index?: number): HogFlowEdge => ({
    from,
    to,
    type,
    index,
})

describe('getWorkflowBranchLabel', () => {
    it.each([
        [false, 'none', 'branch', 'Condition matched'],
        [false, 'targetless', 'branch', 'Condition matched'],
        [false, 'targeted', 'branch', 'Event received'],
        [true, 'none', 'branch', 'Condition matched'],
        [true, 'targetless', 'branch', 'Condition matched'],
        [true, 'targeted', 'branch', 'Condition or event matched'],
        [false, 'none', 'continue', 'No match within 2d'],
        [false, 'targeted', 'continue', 'No match within 2d'],
    ] as const)(
        'labels wait outcomes for condition=%s events=%s and edge=%s',
        (hasCondition, events, edgeType, label) => {
            const eventConfigs = {
                none: [],
                targetless: [{ filters: { events: [], actions: [] } }],
                targeted: [{ filters: { events: [{ id: 'activated' }] } }],
            }
            const waitAction: HogFlowAction = {
                id: 'wait',
                type: 'wait_until_condition',
                name: 'Wait for activation',
                description: '',
                config: {
                    condition: hasCondition ? { filters: { properties: [{ key: 'plan', value: 'pro' }] } } : {},
                    max_wait_duration: '2d',
                    events: eventConfigs[events],
                },
            }
            expect(getWorkflowBranchLabel(waitAction, edge('wait', 'next', edgeType, 0))).toBe(label)
        }
    )

    it.each([
        ['2d', 'No match within 2d'],
        ['31d', 'No match within 30d'],
        ['25h', 'No match within 24h'],
        ['90m', 'No match within 60m'],
        ['m', 'No match'],
        ['', 'No match'],
        [undefined, 'No match'],
    ] as const)('labels a wait timeout of %s on the continue edge', (maxWaitDuration, label) => {
        const waitAction = {
            id: 'wait',
            type: 'wait_until_condition',
            name: 'Wait for activation',
            description: '',
            config: { condition: {}, events: [], max_wait_duration: maxWaitDuration },
        } as HogFlowAction
        expect(getWorkflowBranchLabel(waitAction, edge('wait', 'next', 'continue'))).toBe(label)
    })

    it.each([
        ['branch', 'Loyal users'],
        ['continue', 'Fallback if no cohort has traffic'],
    ] as const)('labels random cohort outcomes for edge=%s', (edgeType, label) => {
        const cohortAction: HogFlowAction = {
            id: 'split',
            type: 'random_cohort_branch',
            name: 'Split traffic',
            description: '',
            config: { cohorts: [{ name: 'Loyal users', percentage: 30 }] },
        }
        expect(getWorkflowBranchLabel(cohortAction, edge('split', 'next', edgeType, 0))).toBe(label)
    })
})
