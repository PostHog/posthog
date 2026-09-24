import type { HogFlow, HogFlowAction, HogFlowEdge } from '../types'
import {
    buildWorkflowTree,
    computeMoveTreeBranchEdges,
    getWorkflowBranchLabel,
    isWorkflowTreeComplete,
} from './workflowTree'
import {
    findWorkflowTreePath,
    getWorkflowTreeBranchSummary,
    getWorkflowTreeContinuationPath,
    getWorkflowTreeStepId,
    getWorkflowTreeStepIds,
} from './workflowTreePresentation'

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
            findWorkflowTreePath(tree, [
                edge('outer', 'trial', 'branch', 1),
                edge('onboarding', 'guided', 'branch', 0),
            ]).map(({ node, branch }) => [node.action.id, branch.edge.index])
        ).toEqual([
            ['outer', 1],
            ['onboarding', 0],
        ])
        expect(
            findWorkflowTreePath(tree, [
                edge('outer', 'trial', 'branch', 1),
                edge('deleted-branch', 'guided', 'branch', 0),
            ])
        ).toEqual([])
    })

    it('keeps a nested join inside the focused path and the outer join outside it', () => {
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('outer', 'conditional_branch'),
                    action('trial'),
                    action('paid'),
                    action('inner', 'conditional_branch'),
                    action('guided'),
                    action('self-serve'),
                    action('followup'),
                    action('shared'),
                    action('exit', 'exit'),
                ],
                [
                    edge('trigger', 'outer'),
                    edge('outer', 'trial', 'branch', 0),
                    edge('outer', 'paid'),
                    edge('trial', 'inner'),
                    edge('inner', 'guided', 'branch', 0),
                    edge('inner', 'self-serve'),
                    edge('guided', 'followup'),
                    edge('self-serve', 'followup'),
                    edge('followup', 'shared'),
                    edge('paid', 'shared'),
                    edge('shared', 'exit'),
                ]
            )
        )

        const [focused] = findWorkflowTreePath(tree, [edge('outer', 'trial', 'branch', 0)])

        expect(focused.branch.sequence.nodes.find((node) => node.action.id === 'inner')?.joinActionId).toBe('followup')
        expect(focused.node.joinActionId).toBe('shared')
        expect([...getWorkflowTreeStepIds(focused.branch.sequence)]).toEqual([
            'trial',
            'inner',
            'guided',
            'self-serve',
            'followup',
        ])
        const innerPath = [edge('outer', 'trial', 'branch', 0), edge('inner', 'guided', 'branch', 0)]
        expect(getWorkflowTreeContinuationPath(tree, innerPath, 'followup')).toEqual(innerPath.slice(0, 1))
        expect(getWorkflowTreeContinuationPath(tree, innerPath, 'shared')).toEqual([])
    })

    it('keeps the selected occurrence when paths share a branching action', () => {
        const tree = buildWorkflowTree(
            workflow(
                [
                    action('trigger', 'trigger'),
                    action('outer', 'conditional_branch'),
                    action('wait', 'wait_until_condition'),
                    action('matched'),
                    action('timeout'),
                    action('exit', 'exit'),
                ],
                [
                    edge('trigger', 'outer'),
                    edge('outer', 'wait', 'branch', 0),
                    edge('outer', 'wait', 'branch', 1),
                    edge('outer', 'exit'),
                    edge('wait', 'matched', 'branch', 0),
                    edge('wait', 'timeout'),
                    edge('matched', 'exit'),
                    edge('timeout', 'exit'),
                ]
            )
        )
        const firstPath = [edge('outer', 'wait', 'branch', 0), edge('wait', 'matched', 'branch', 0)]
        const secondPath = [edge('outer', 'wait', 'branch', 1), edge('wait', 'matched', 'branch', 0)]

        for (const path of [firstPath, secondPath]) {
            expect(findWorkflowTreePath(tree, path).map(({ branch }) => branch.edge)).toEqual(path)
            expect(getWorkflowTreeContinuationPath(tree, path, 'matched')).toEqual(path)
        }
        expect(getWorkflowTreeStepId('matched', firstPath)).not.toBe(getWorkflowTreeStepId('matched', secondPath))
        expect(findWorkflowTreePath(tree, [edge('wait', 'matched', 'branch', 0)])).toEqual([])
    })

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
