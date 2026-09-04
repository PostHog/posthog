import { getLinearWorkflowActionIds } from './linearWorkflow'
import type { HogFlow, HogFlowAction } from './types'

const action = (id: string, type: HogFlowAction['type']): HogFlowAction => ({ id, type }) as HogFlowAction

const workflow = (actions: HogFlowAction[], edges: HogFlow['edges']): Pick<HogFlow, 'actions' | 'edges'> => ({
    actions,
    edges,
})

describe('getLinearWorkflowActionIds', () => {
    it('orders a trigger-to-exit sequence', () => {
        expect(
            getLinearWorkflowActionIds(
                workflow(
                    [action('trigger', 'trigger'), action('slack', 'function'), action('exit', 'exit')],
                    [
                        { from: 'trigger', to: 'slack', type: 'continue' },
                        { from: 'slack', to: 'exit', type: 'continue' },
                    ]
                )
            )
        ).toEqual(['trigger', 'slack', 'exit'])
    })

    it.each([
        {
            name: 'a conditional step',
            actions: [action('trigger', 'trigger'), action('condition', 'conditional_branch'), action('exit', 'exit')],
            edges: [
                { from: 'trigger', to: 'condition', type: 'continue' as const },
                { from: 'condition', to: 'exit', type: 'continue' as const },
            ],
        },
        {
            name: 'a graph with converging paths',
            actions: [
                action('trigger', 'trigger'),
                action('first', 'function'),
                action('second', 'function'),
                action('exit', 'exit'),
            ],
            edges: [
                { from: 'trigger', to: 'first', type: 'continue' as const },
                { from: 'trigger', to: 'second', type: 'continue' as const },
                { from: 'first', to: 'exit', type: 'continue' as const },
            ],
        },
    ])('rejects $name', ({ actions, edges }) => {
        expect(getLinearWorkflowActionIds(workflow(actions, edges))).toBeNull()
    })
})
