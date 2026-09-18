import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'
import {
    buildWorkflowTree,
    computeMoveTreeBranchEdges,
    getWorkflowBranchLabel,
    isWorkflowTreeComplete,
} from './workflowTree'
import { findWorkflowTreePath, getWorkflowTreeBranchSummary } from './workflowTreePresentation'

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
    it('falls back when an action is unreachable from the trigger', () => {
        expect(
            isWorkflowTreeComplete(
                workflow(
                    [action('trigger', 'trigger'), action('exit', 'exit'), action('orphan')],
                    [edge('trigger', 'exit')]
                )
            )
        ).toBe(false)
    })

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
        expect(tree.nodes[1].joinAction?.id).toBe('shared')
        expect(getWorkflowTreeBranchSummary(tree.nodes[1], tree.nodes[1].branches[0])).toBe(
            '1 step · Continue to: shared'
        )
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
        expect(getWorkflowTreeBranchSummary(tree.nodes[1], tree.nodes[1].branches[0])).toBe(
            '0 steps · Continue to: exit'
        )
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
        expect(getWorkflowTreeBranchSummary(tree.nodes[1], tree.nodes[1].branches[0])).toBe('1 step · End workflow')
    })

    it('scopes a nested branch join to its own routes', () => {
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('outer', 'conditional_branch'),
                    action('paid'),
                    action('trial'),
                    action('at-risk'),
                    action('onboarding', 'conditional_branch'),
                    action('guided'),
                    action('self-serve'),
                    action('shared'),
                    action('exit', 'exit'),
                ],
                [
                    edge('trigger', 'outer'),
                    edge('outer', 'paid', 'branch', 0),
                    edge('outer', 'trial', 'branch', 1),
                    edge('outer', 'at-risk'),
                    edge('paid', 'shared'),
                    edge('trial', 'onboarding'),
                    edge('at-risk', 'shared'),
                    edge('onboarding', 'guided', 'branch', 0),
                    edge('onboarding', 'self-serve', 'branch', 1),
                    edge('onboarding', 'shared'),
                    edge('guided', 'shared'),
                    edge('self-serve', 'shared'),
                    edge('shared', 'exit'),
                ]
            )
        )

        const onboarding = tree.nodes[1].branches[1].sequence.nodes.find((node) => node.action.id === 'onboarding')
        expect(onboarding?.joinEdges).toEqual([
            edge('guided', 'shared'),
            edge('self-serve', 'shared'),
            edge('onboarding', 'shared'),
        ])
        expect(getWorkflowTreeBranchSummary(tree.nodes[1], tree.nodes[1].branches[1])).toBe(
            '4 steps · Continue to: shared'
        )
        expect(
            findWorkflowTreePath(tree, edge('onboarding', 'guided', 'branch', 0)).map(({ node, branch }) => [
                node.action.id,
                branch.edge.index,
            ])
        ).toEqual([
            ['outer', 1],
            ['onboarding', 0],
        ])
        expect(findWorkflowTreePath(tree, edge('deleted-branch', 'guided', 'branch', 0))).toEqual([])
    })

    it.each([
        [false, false, 'branch', 'Condition matched'],
        [false, true, 'branch', 'Event received'],
        [true, false, 'branch', 'Condition matched'],
        [true, true, 'branch', 'Condition or event matched'],
        [false, false, 'continue', 'No match within 2d'],
        [false, true, 'continue', 'No match within 2d'],
    ] as const)(
        'labels wait outcomes for condition=%s events=%s and edge=%s',
        (hasCondition, hasEvents, edgeType, label) => {
            const waitAction: HogFlowAction = {
                id: 'wait',
                type: 'wait_until_condition',
                name: 'Wait for activation',
                description: '',
                config: {
                    condition: hasCondition ? { filters: { properties: [{ key: 'plan', value: 'pro' }] } } : {},
                    max_wait_duration: '2d',
                    events: hasEvents ? [{ name: 'activated' }] : [],
                },
            }
            expect(getWorkflowBranchLabel(waitAction, edge('wait', 'next', edgeType, 0))).toBe(label)
        }
    )

    it('moves a branching action with all of its paths', () => {
        const workflowWithJoin = workflow(
            [
                action('trigger', 'trigger'),
                action('condition', 'conditional_branch'),
                action('yes'),
                action('no'),
                action('shared'),
                action('after'),
                action('exit', 'exit'),
            ],
            [
                edge('trigger', 'condition'),
                edge('condition', 'yes', 'branch', 0),
                edge('condition', 'no'),
                edge('yes', 'shared'),
                edge('no', 'shared'),
                edge('shared', 'after'),
                edge('after', 'exit'),
            ]
        )

        expect(computeMoveTreeBranchEdges(workflowWithJoin, 'condition', edge('shared', 'after'), false)).toEqual([
            edge('trigger', 'shared'),
            edge('condition', 'yes', 'branch', 0),
            edge('condition', 'no'),
            edge('yes', 'after'),
            edge('no', 'after'),
            edge('after', 'exit'),
            edge('shared', 'condition'),
        ])
    })
})
