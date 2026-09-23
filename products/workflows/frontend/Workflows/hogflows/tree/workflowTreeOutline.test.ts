import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'
import { buildWorkflowTree } from './workflowTree'
import { buildWorkflowTreeOutline } from './workflowTreeOutline'
import { getWorkflowTreePathHeaderId, getWorkflowTreeStepId } from './workflowTreePresentation'

const action = (id: string, type: HogFlowAction['type'] = 'function'): HogFlowAction =>
    ({ id, type, name: id, description: '', config: {} }) as HogFlowAction

const edge = (from: string, to: string, type: HogFlowEdge['type'] = 'continue', index?: number): HogFlowEdge => ({
    from,
    to,
    type,
    index,
})

const workflow = (actions: HogFlowAction[], edges: HogFlowEdge[]): Pick<HogFlow, 'actions' | 'edges'> => ({
    actions,
    edges,
})

describe('buildWorkflowTreeOutline', () => {
    it('lists every step and path in reading order with the ids the tree renders', () => {
        const outerBranch = edge('outer', 'inner', 'branch', 0)
        const innerBranch = edge('inner', 'nested-step', 'branch', 0)
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('outer', 'conditional_branch'),
                    action('inner', 'conditional_branch'),
                    action('nested-step'),
                    action('shared'),
                    action('exit', 'exit'),
                ],
                [
                    edge('trigger', 'outer'),
                    outerBranch,
                    edge('outer', 'shared'),
                    innerBranch,
                    edge('inner', 'shared'),
                    edge('nested-step', 'shared'),
                    edge('shared', 'exit'),
                ]
            )
        )

        const rows = buildWorkflowTreeOutline(tree)

        expect(rows.map((row) => [row.kind, row.label, row.depth, row.stepCount])).toEqual([
            ['step', 'trigger', 0, null],
            ['step', 'outer', 0, null],
            ['path', 'If condition #1 matches', 1, 2],
            ['step', 'inner', 2, null],
            ['path', 'If condition #1 matches', 3, 1],
            ['step', 'nested-step', 4, null],
            ['path', 'No match', 3, 0],
            ['path', 'No match', 1, 0],
            ['step', 'shared', 0, null],
            ['step', 'exit', 0, null],
        ])
        expect(rows.map((row) => row.targetId)).toEqual([
            getWorkflowTreeStepId('trigger', []),
            getWorkflowTreeStepId('outer', []),
            getWorkflowTreePathHeaderId('outer', [outerBranch]),
            getWorkflowTreeStepId('inner', [outerBranch]),
            getWorkflowTreePathHeaderId('inner', [outerBranch, innerBranch]),
            getWorkflowTreeStepId('nested-step', [outerBranch, innerBranch]),
            getWorkflowTreePathHeaderId('inner', [outerBranch, edge('inner', 'shared')]),
            getWorkflowTreePathHeaderId('outer', [edge('outer', 'shared')]),
            getWorkflowTreeStepId('shared', []),
            getWorkflowTreeStepId('exit', []),
        ])
    })
})
