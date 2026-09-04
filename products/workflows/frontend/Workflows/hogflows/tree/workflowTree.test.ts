import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'
import { buildWorkflowTree } from './workflowTree'

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

describe('buildWorkflowTree', () => {
    it('renders converging routes before one shared continuation', () => {
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('condition', 'conditional_branch'),
                    action('yes'),
                    action('no'),
                    action('shared'),
                    action('exit', 'exit'),
                ],
                [
                    edge('trigger', 'condition'),
                    edge('condition', 'yes', 'branch', 0),
                    edge('condition', 'no'),
                    edge('yes', 'shared'),
                    edge('no', 'shared'),
                    edge('shared', 'exit'),
                ]
            )
        )

        expect(tree.nodes.map((node) => node.action.id)).toEqual(['trigger', 'condition', 'shared', 'exit'])
        expect(tree.nodes[1].branches.map((branch) => branch.sequence.nodes.map((node) => node.action.id))).toEqual([
            ['yes'],
            ['no'],
        ])
        expect(tree.nodes[1].joinActionId).toBe('shared')
    })

    it('keeps immediate routes empty and exposes their insertion edges', () => {
        const tree = buildWorkflowTree(
            workflow(
                [action('trigger', 'trigger'), action('condition', 'conditional_branch'), action('exit', 'exit')],
                [edge('trigger', 'condition'), edge('condition', 'exit', 'branch', 0), edge('condition', 'exit')]
            )
        )

        expect(tree.nodes.map((node) => node.action.id)).toEqual(['trigger', 'condition', 'exit'])
        expect(tree.nodes[1].branches.map((branch) => branch.sequence.nodes)).toEqual([[], []])
        expect(tree.nodes[1].branches.map((branch) => branch.sequence.trailingEdge)).toEqual([
            edge('condition', 'exit', 'branch', 0),
            edge('condition', 'exit'),
        ])
    })

    it('leaves routes terminal when they have no shared continuation', () => {
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('condition', 'conditional_branch'),
                    action('left-exit', 'exit'),
                    action('right-exit', 'exit'),
                ],
                [
                    edge('trigger', 'condition'),
                    edge('condition', 'left-exit', 'branch', 0),
                    edge('condition', 'right-exit'),
                ]
            )
        )

        expect(tree.nodes.map((node) => node.action.id)).toEqual(['trigger', 'condition'])
        expect(tree.nodes[1].joinActionId).toBeNull()
        expect(tree.nodes[1].branches.map((branch) => branch.sequence.nodes.map((node) => node.action.id))).toEqual([
            ['left-exit'],
            ['right-exit'],
        ])
    })
})
