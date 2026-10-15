import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from '../workflowLogic'
import { CreateActionType, computeInsertEdges, computeMoveEdges, hogFlowEditorLogic } from './hogFlowEditorLogic'
import { CLASSIFY_ACTION_NODE, DELAY_NODES_TO_SHOW } from './stepPicker/stepDefinitions'
import { HogFlow, HogFlowAction, HogFlowActionEdge, HogFlowActionNode } from './types'

jest.mock('posthog-js')

type Edge = HogFlow['edges'][0]
const edge = (from: string, to: string, type: 'continue' | 'branch', index?: number): Edge => ({
    from,
    to,
    type,
    index,
})

describe('computeMoveEdges', () => {
    it.each([
        {
            name: 'move node forward in linear chain',
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'B', 'continue'), edge('B', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('B', 'exit', 'continue'),
            isBranchJoin: false,
            expected: [edge('trigger', 'B', 'continue'), edge('B', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node backward in linear chain',
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'B', 'continue'), edge('B', 'exit', 'continue')],
            movingNodeId: 'B',
            targetEdge: edge('trigger', 'A', 'continue'),
            isBranchJoin: false,
            expected: [edge('A', 'exit', 'continue'), edge('trigger', 'B', 'continue'), edge('B', 'A', 'continue')],
        },
        {
            name: 'move node from continue branch to branch edge of conditional',
            edges: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node from branch edge to continue branch of conditional',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'exit', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'continue'),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node onto edge it is already the target of (no-op position)',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'exit', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'A', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node to branch join dropzone inserts on all branches',
            edges: [edge('cond', 'exit', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'exit', 'branch', 0),
            isBranchJoin: true,
            expected: [edge('cond', 'A', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'move node when both conditional edges point to it (branch join, move to branch)',
            edges: [edge('cond', 'A', 'branch', 0), edge('cond', 'A', 'continue'), edge('A', 'exit', 'continue')],
            movingNodeId: 'A',
            targetEdge: edge('cond', 'A', 'branch', 0),
            isBranchJoin: false,
            expected: [edge('cond', 'exit', 'continue'), edge('cond', 'A', 'branch', 0), edge('A', 'exit', 'continue')],
        },
    ])('$name', ({ edges, movingNodeId, targetEdge, isBranchJoin, expected }) => {
        const result = computeMoveEdges(edges, movingNodeId, targetEdge, isBranchJoin)
        expect(result).toEqual(expected)
    })

    it('inserts a step after only the nested split paths', () => {
        const edges = [
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('onboarding', 'shared', 'continue'),
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('shared', 'exit', 'continue'),
        ]

        expect(
            computeInsertEdges(edges, 'after-onboarding', 0, [
                edge('guided', 'shared', 'continue'),
                edge('self-serve', 'shared', 'continue'),
                edge('onboarding', 'shared', 'continue'),
            ])
        ).toEqual([
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('shared', 'exit', 'continue'),
            edge('onboarding', 'after-onboarding', 'continue'),
            edge('guided', 'after-onboarding', 'continue'),
            edge('self-serve', 'after-onboarding', 'continue'),
            edge('after-onboarding', 'shared', 'continue'),
        ])
    })

    it('moves a step after only the nested split paths', () => {
        const edges = [
            edge('trigger', 'move', 'continue'),
            edge('move', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('onboarding', 'shared', 'continue'),
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('shared', 'exit', 'continue'),
        ]
        const joinEdges = [
            edge('guided', 'shared', 'continue'),
            edge('self-serve', 'shared', 'continue'),
            edge('onboarding', 'shared', 'continue'),
        ]

        expect(computeMoveEdges(edges, 'move', joinEdges[0], true, joinEdges)).toEqual([
            edge('trigger', 'outer', 'continue'),
            edge('outer', 'paid', 'branch', 0),
            edge('outer', 'onboarding', 'branch', 1),
            edge('outer', 'at-risk', 'continue'),
            edge('paid', 'shared', 'continue'),
            edge('at-risk', 'shared', 'continue'),
            edge('onboarding', 'guided', 'branch', 0),
            edge('onboarding', 'self-serve', 'branch', 1),
            edge('shared', 'exit', 'continue'),
            edge('onboarding', 'move', 'continue'),
            edge('guided', 'move', 'continue'),
            edge('self-serve', 'move', 'continue'),
            edge('move', 'shared', 'continue'),
        ])
    })

    it('returns null when moving node has no outgoing edge', () => {
        const edges = [edge('trigger', 'A', 'continue')]
        expect(computeMoveEdges(edges, 'A', edge('trigger', 'A', 'continue'), false)).toBeNull()
    })

    it('returns null when target edge cannot be found after bypass', () => {
        const edges = [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')]
        const nonexistent = edge('X', 'Y', 'continue')
        expect(computeMoveEdges(edges, 'A', nonexistent, false)).toBeNull()
    })
})

describe('hogFlowEditorLogic', () => {
    let logic: ReturnType<typeof hogFlowEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = hogFlowEditorLogic()
        logic.mount()
    })

    it('resolves the selected action while React Flow nodes are still laying out', () => {
        const action = logic.values.workflow.actions[0]
        logic.actions.setNodesRaw([])
        logic.actions.setSelectedNodeId(action.id)

        expect(logic.values.selectedNode).toMatchObject({ id: action.id, data: action })
    })

    it('duplicates a linear step below itself', () => {
        const delay: HogFlowAction = {
            id: 'delay',
            name: 'Delay',
            description: '',
            type: 'delay',
            created_at: 0,
            updated_at: 0,
            config: { delay_duration: '1d' },
        }
        workflowLogic().actions.setWorkflowInfo({
            actions: [NEW_WORKFLOW.actions[0], delay, NEW_WORKFLOW.actions[1]],
            edges: [edge(TRIGGER_NODE_ID, delay.id, 'continue'), edge(delay.id, EXIT_NODE_ID, 'continue')],
        })

        logic.actions.duplicateNodeBelow(delay.id)

        const duplicatedAction = logic.values.workflow.actions.find(
            (action) => action.id !== delay.id && action.type === delay.type
        )
        expect(duplicatedAction).toMatchObject({ name: delay.name, config: delay.config })
        expect(logic.values.workflow.edges).toEqual([
            edge(TRIGGER_NODE_ID, delay.id, 'continue'),
            edge(delay.id, duplicatedAction!.id, 'continue'),
            edge(duplicatedAction!.id, EXIT_NODE_ID, 'continue'),
        ])
    })

    describe('conditional branch naming', () => {
        const createMockHogFlow = (conditionNames?: (string | undefined)[]): HogFlow => ({
            id: 'test-flow',
            team_id: 1,
            version: 1,
            name: 'Test Flow',
            status: 'draft',
            exit_condition: 'exit_only_at_end',
            actions: [
                {
                    id: 'trigger',
                    name: 'Trigger',
                    description: '',
                    type: 'trigger',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    config: {
                        type: 'event',
                        filters: {},
                    },
                },
                {
                    id: 'branch',
                    name: 'Conditional Branch',
                    description: '',
                    type: 'conditional_branch',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    config: {
                        conditions: conditionNames
                            ? conditionNames.map((name) => ({ filters: {}, name }))
                            : [{ filters: {} }, { filters: {} }],
                    },
                },
                {
                    id: 'exit',
                    name: 'Exit',
                    description: '',
                    type: 'exit',
                    created_at: Date.now(),
                    updated_at: Date.now(),
                    config: { reason: '' },
                },
            ],
            edges: [
                { from: 'trigger', to: 'branch', type: 'continue' },
                { from: 'branch', to: 'exit', type: 'branch', index: 0 },
                { from: 'branch', to: 'exit', type: 'branch', index: 1 },
                { from: 'branch', to: 'exit', type: 'continue' },
            ],
            updated_at: new Date().toISOString(),
            created_at: new Date().toISOString(),
        })

        it('should use default labels when condition names are not provided', () => {
            const mockFlow = createMockHogFlow()
            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges

            // Find the branch edges
            const branchEdge0 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_0'))
            const branchEdge1 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_1'))
            const continueEdge = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('continue_branch'))

            expect(branchEdge0?.data?.label).toBe('If condition #1 matches')
            expect(branchEdge1?.data?.label).toBe('If condition #2 matches')
            expect(continueEdge?.data?.label).toBe('No match')
        })

        it('should use custom names when provided for conditional branches', () => {
            const mockFlow = createMockHogFlow(['User is premium', 'User is in trial'])
            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges

            // Find the branch edges
            const branchEdge0 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_0'))
            const branchEdge1 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_1'))
            const continueEdge = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('continue_branch'))

            expect(branchEdge0?.data?.label).toBe('User is premium')
            expect(branchEdge1?.data?.label).toBe('User is in trial')
            expect(continueEdge?.data?.label).toBe('No match')
        })

        it('should fall back to default labels for conditions without names', () => {
            const mockFlow = createMockHogFlow(['User is premium', undefined])
            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges

            // Find the branch edges
            const branchEdge0 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_0'))
            const branchEdge1 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_1'))

            expect(branchEdge0?.data?.label).toBe('User is premium')
            expect(branchEdge1?.data?.label).toBe('If condition #2 matches')
        })

        it('should not show labels for single-edge nodes', () => {
            const mockFlow = createMockHogFlow()
            // Remove all but one edge from the branch node
            mockFlow.edges = [
                { from: 'trigger', to: 'branch', type: 'continue' },
                { from: 'branch', to: 'exit', type: 'continue' },
            ]

            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges
            const branchEdge = edges.find((e) => e.source === 'branch')

            expect(branchEdge?.data?.label).toBeUndefined()
        })

        it('should update edge labels when conditions are modified', () => {
            const mockFlow = createMockHogFlow()
            logic.actions.resetFlowFromHogFlow(mockFlow)

            // Update the action with new condition names
            const updatedAction: HogFlowAction = {
                id: 'branch',
                name: 'Conditional Branch',
                description: '',
                type: 'conditional_branch',
                created_at: Date.now(),
                updated_at: Date.now(),
                config: {
                    conditions: [
                        { filters: {}, name: 'New condition 1' },
                        { filters: {}, name: 'New condition 2' },
                    ],
                },
            }

            logic.actions.setWorkflowAction('branch', updatedAction)

            // Re-trigger the flow reset to update edges
            const updatedFlow = {
                ...mockFlow,
                actions: mockFlow.actions.map((a) => (a.id === 'branch' ? updatedAction : a)),
            }
            logic.actions.resetFlowFromHogFlow(updatedFlow)

            const edges = logic.values.edges
            const branchEdge0 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_0'))
            const branchEdge1 = edges.find((e) => e.source === 'branch' && e.sourceHandle?.includes('branch_branch_1'))

            expect(branchEdge0?.data?.label).toBe('New condition 1')
            expect(branchEdge1?.data?.label).toBe('New condition 2')
        })

        it('should use custom names for wait_until_condition when provided', () => {
            const mockFlow: HogFlow = {
                ...createMockHogFlow(),
                actions: [
                    {
                        id: 'trigger',
                        name: 'Trigger',
                        description: '',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'event',
                            filters: {},
                        },
                    },
                    {
                        id: 'wait',
                        name: 'Wait Until',
                        description: '',
                        type: 'wait_until_condition',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            condition: { filters: {}, name: 'User completes onboarding' },
                            max_wait_duration: '1h',
                        },
                    },
                    {
                        id: 'exit',
                        name: 'Exit',
                        description: '',
                        type: 'exit',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: { reason: '' },
                    },
                ],
                edges: [
                    { from: 'trigger', to: 'wait', type: 'continue' },
                    { from: 'wait', to: 'exit', type: 'branch', index: 0 },
                    { from: 'wait', to: 'exit', type: 'continue' },
                ],
            }

            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges
            const branchEdge = edges.find((e) => e.source === 'wait' && e.sourceHandle?.includes('branch_wait_0'))

            expect(branchEdge?.data?.label).toBe('User completes onboarding')
        })

        it('should handle wait_until_condition edge labels without custom names', () => {
            const mockFlow: HogFlow = {
                ...createMockHogFlow(),
                actions: [
                    {
                        id: 'trigger',
                        name: 'Trigger',
                        description: '',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'event',
                            filters: {},
                        },
                    },
                    {
                        id: 'wait',
                        name: 'Wait Until',
                        description: '',
                        type: 'wait_until_condition',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            condition: { filters: {} },
                            max_wait_duration: '1h',
                        },
                    },
                    {
                        id: 'exit',
                        name: 'Exit',
                        description: '',
                        type: 'exit',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: { reason: '' },
                    },
                ],
                edges: [
                    { from: 'trigger', to: 'wait', type: 'continue' },
                    { from: 'wait', to: 'exit', type: 'branch', index: 0 },
                    { from: 'wait', to: 'exit', type: 'continue' },
                ],
            }

            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges
            const branchEdge = edges.find((e) => e.source === 'wait' && e.sourceHandle?.includes('branch_wait_0'))

            expect(branchEdge?.data?.label).toBe('If condition matches')
        })

        it('should use custom names for random_cohort_branch when provided', () => {
            const mockFlow: HogFlow = {
                ...createMockHogFlow(),
                actions: [
                    {
                        id: 'trigger',
                        name: 'Trigger',
                        description: '',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'event',
                            filters: {},
                        },
                    },
                    {
                        id: 'cohort',
                        name: 'Random Cohort',
                        description: '',
                        type: 'random_cohort_branch',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            cohorts: [
                                { percentage: 50, name: 'Control group' },
                                { percentage: 50, name: 'Test group' },
                            ],
                        },
                    },
                    {
                        id: 'exit',
                        name: 'Exit',
                        description: '',
                        type: 'exit',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: { reason: '' },
                    },
                ],
                edges: [
                    { from: 'trigger', to: 'cohort', type: 'continue' },
                    { from: 'cohort', to: 'exit', type: 'branch', index: 0 },
                    { from: 'cohort', to: 'exit', type: 'branch', index: 1 },
                ],
            }

            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges
            const branchEdge0 = edges.find((e) => e.source === 'cohort' && e.sourceHandle?.includes('branch_cohort_0'))
            const branchEdge1 = edges.find((e) => e.source === 'cohort' && e.sourceHandle?.includes('branch_cohort_1'))

            expect(branchEdge0?.data?.label).toBe('Control group')
            expect(branchEdge1?.data?.label).toBe('Test group')
        })

        it('should handle random_cohort_branch edge labels without custom names', () => {
            const mockFlow: HogFlow = {
                ...createMockHogFlow(),
                actions: [
                    {
                        id: 'trigger',
                        name: 'Trigger',
                        description: '',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'event',
                            filters: {},
                        },
                    },
                    {
                        id: 'cohort',
                        name: 'Random Cohort',
                        description: '',
                        type: 'random_cohort_branch',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            cohorts: [{ percentage: 50 }, { percentage: 50 }],
                        },
                    },
                    {
                        id: 'exit',
                        name: 'Exit',
                        description: '',
                        type: 'exit',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: { reason: '' },
                    },
                ],
                edges: [
                    { from: 'trigger', to: 'cohort', type: 'continue' },
                    { from: 'cohort', to: 'exit', type: 'branch', index: 0 },
                    { from: 'cohort', to: 'exit', type: 'branch', index: 1 },
                ],
            }

            logic.actions.resetFlowFromHogFlow(mockFlow)

            const edges = logic.values.edges
            const branchEdge0 = edges.find((e) => e.source === 'cohort' && e.sourceHandle?.includes('branch_cohort_0'))
            const branchEdge1 = edges.find((e) => e.source === 'cohort' && e.sourceHandle?.includes('branch_cohort_1'))

            expect(branchEdge0?.data?.label).toBe('If cohort #1 matches')
            expect(branchEdge1?.data?.label).toBe('If cohort #2 matches')
        })
    })

    describe('graph identity across rebuilds', () => {
        // Auto-save round-trips rebuild the graph from the workflow; without id-based
        // reconciliation every node and edge object is recreated each time and every ReactFlow
        // subtree re-renders, the detached-DOM churn this exists to prevent. Fixed timestamps so
        // two calls produce deep-equal flows.
        const makeFlow = (branchName: string = 'Branch'): HogFlow => ({
            id: 'test-flow',
            team_id: 1,
            version: 1,
            name: 'Test Flow',
            status: 'draft',
            exit_condition: 'exit_only_at_end',
            actions: [
                {
                    id: 'trigger',
                    name: 'Trigger',
                    description: '',
                    type: 'trigger',
                    created_at: 1,
                    updated_at: 1,
                    config: { type: 'event', filters: {} },
                },
                {
                    id: 'branch',
                    name: branchName,
                    description: '',
                    type: 'conditional_branch',
                    created_at: 1,
                    updated_at: 1,
                    config: { conditions: [{ filters: {} }] },
                },
                {
                    id: 'exit',
                    name: 'Exit',
                    description: '',
                    type: 'exit',
                    created_at: 1,
                    updated_at: 1,
                    config: { reason: '' },
                },
            ],
            edges: [
                { from: 'trigger', to: 'branch', type: 'continue' },
                { from: 'branch', to: 'exit', type: 'branch', index: 0 },
                { from: 'branch', to: 'exit', type: 'continue' },
            ],
            updated_at: '2026-01-01T00:00:00Z',
            created_at: '2026-01-01T00:00:00Z',
        })

        // Each rebuild finishes by dispatching setNodesRaw from the async layout listener, and
        // kea-test-utils consumes matched actions in order, so awaiting one setNodesRaw per
        // rebuild is the deterministic "layout finished" signal.
        const applyFlow = async (flow: HogFlow): Promise<void> => {
            await expectLogic(logic, () => logic.actions.resetFlowFromHogFlow(flow)).toDispatchActions(['setNodesRaw'])
        }

        beforeEach(async () => {
            // Let the mount-time subscription rebuild (from workflowLogic's template flow) land
            // first so it can't clobber the flows the tests apply.
            await expectLogic(logic).toDispatchActions(['setNodesRaw'])
        })

        it('keeps node and edge references stable across a deep-equal rebuild', async () => {
            await applyFlow(makeFlow())
            const initialNodes = logic.values.nodes
            const initialEdges = logic.values.edges
            expect(initialNodes.length).toBeGreaterThan(0)

            // Freshly constructed but deep-equal, as an auto-save round-trip would deliver.
            await applyFlow(makeFlow())

            // Array identity, not just item identity: ReactFlow diffs its nodes/edges props by
            // reference, so a fresh array wrapper per rebuild re-syncs its store every render.
            expect(logic.values.nodes).toBe(initialNodes)
            expect(logic.values.edges).toBe(initialEdges)
        })

        it('replaces only the changed node reference when one action changes', async () => {
            await applyFlow(makeFlow())
            const initialNodes = logic.values.nodes

            await applyFlow(makeFlow('Renamed branch'))

            const byId = (id: string): HogFlowActionNode | undefined =>
                logic.values.nodes.find((node) => node.id === id)
            expect(byId('trigger')).toBe(initialNodes.find((node) => node.id === 'trigger'))
            expect(byId('exit')).toBe(initialNodes.find((node) => node.id === 'exit'))
            expect(byId('branch')).not.toBe(initialNodes.find((node) => node.id === 'branch'))
            expect(byId('branch')?.data.name).toBe('Renamed branch')
        })
    })

    describe('placing a new step', () => {
        const BRANCH_ID = 'route-by-plan'
        const conditionalBranch: HogFlowAction = {
            id: BRANCH_ID,
            type: 'conditional_branch',
            name: 'Route by plan',
            description: '',
            created_at: 0,
            updated_at: 0,
            config: { conditions: [{ name: 'Paid', filters: {} }] },
        }
        const delay: HogFlowAction = {
            id: 'delay',
            name: 'Delay',
            description: '',
            type: 'delay',
            created_at: 0,
            updated_at: 0,
            config: { delay_duration: '1d' },
        }

        const captures = (): [string, Record<string, any>][] => (posthog.capture as jest.Mock).mock.calls as any
        const capturedEvent = (name: string): Record<string, any>[] =>
            captures()
                .filter(([event]) => event === name)
                .map(([, properties]) => properties)
        const addedActions = (): HogFlowAction[] =>
            logic.values.workflow.actions.filter(
                (action) => ![TRIGGER_NODE_ID, EXIT_NODE_ID, BRANCH_ID, delay.id].includes(action.id)
            )

        const setWorkflow = async (actions: HogFlowAction[], edges: Edge[]): Promise<void> => {
            await expectLogic(logic, () =>
                workflowLogic().actions.setWorkflowInfo({ actions, edges })
            ).toDispatchActions(['setNodesRaw'])
        }
        const highlightDropzone = (from: string, to: string, isBranchJoin: boolean): void => {
            const dropzone = logic.values.dropzoneNodes.find(
                (node) =>
                    node.data.edge.source === from &&
                    node.data.edge.target === to &&
                    !!node.data.isBranchJoinDropzone === isBranchJoin
            )
            logic.actions.setHighlightedDropzoneNodeId(dropzone!.id)
        }

        beforeEach(async () => {
            ;(posthog.capture as jest.Mock).mockClear()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_STEP_PICKER], {
                [FEATURE_FLAGS.WORKFLOWS_STEP_PICKER]: true,
            })
            await expectLogic(logic).toDispatchActions(['setNodesRaw'])
        })

        it.each([
            {
                name: 'a highlighted graph dropzone',
                actions: NEW_WORKFLOW.actions,
                edges: [edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue')],
                place: () => {
                    highlightDropzone(TRIGGER_NODE_ID, EXIT_NODE_ID, false)
                    logic.actions.placeNewStep()
                },
                expectedEdges: (added: string) => [
                    edge(TRIGGER_NODE_ID, added, 'continue'),
                    edge(added, EXIT_NODE_ID, 'continue'),
                ],
            },
            {
                name: 'a tree insertion point',
                actions: NEW_WORKFLOW.actions,
                edges: [edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue')],
                place: () => logic.actions.placeNewStep(edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue')),
                expectedEdges: (added: string) => [
                    edge(TRIGGER_NODE_ID, added, 'continue'),
                    edge(added, EXIT_NODE_ID, 'continue'),
                ],
            },
            {
                name: 'a tree branch join',
                actions: [NEW_WORKFLOW.actions[0], conditionalBranch, NEW_WORKFLOW.actions[1]],
                edges: [
                    edge(TRIGGER_NODE_ID, BRANCH_ID, 'continue'),
                    edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0),
                    edge(BRANCH_ID, EXIT_NODE_ID, 'continue'),
                ],
                place: () =>
                    logic.actions.placeNewStep(edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0), [
                        edge(BRANCH_ID, EXIT_NODE_ID, 'branch', 0),
                        edge(BRANCH_ID, EXIT_NODE_ID, 'continue'),
                    ]),
                expectedEdges: (added: string) => [
                    edge(TRIGGER_NODE_ID, BRANCH_ID, 'continue'),
                    edge(BRANCH_ID, added, 'branch', 0),
                    edge(BRANCH_ID, added, 'continue'),
                    edge(added, EXIT_NODE_ID, 'continue'),
                ],
            },
        ])('places the picked step at $name', async ({ actions, edges, place, expectedEdges }) => {
            await setWorkflow(actions, edges)

            logic.actions.startPlacingNewStep(CLASSIFY_ACTION_NODE)
            expect(logic.values.isPlacingNewStep).toBe(true)
            expect(logic.values.dropzoneNodes.length).toBeGreaterThan(0)

            place()

            const [added] = addedActions()
            expect(added).toMatchObject({
                type: 'function',
                name: 'Classify with AI',
                config: { template_id: 'template-posthog-classify' },
                output_variable: CLASSIFY_ACTION_NODE.output_variable,
            })
            expect(logic.values.workflow.edges).toEqual(expectedEdges(added.id))
            expect(logic.values.workflow.variables?.map((variable) => variable.key)).toEqual(
                expect.arrayContaining(['category', 'confidence'])
            )
            expect(logic.values.isPlacingNewStep).toBe(false)
            expect(logic.values.dropzoneNodes).toEqual([])
            expect(capturedEvent('workflow step placement finished')).toEqual([
                { step_id: 'template-posthog-classify', outcome: 'placed' },
            ])
        })

        it.each([
            {
                name: 'Escape',
                cancel: () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })),
            },
            { name: 'a click on the empty canvas', cancel: () => logic.actions.handlePaneClick() },
            { name: 'Cancel', cancel: () => logic.actions.cancelPlacingNewStep() },
        ])('stops placement without inserting on $name', async ({ cancel }) => {
            await setWorkflow(NEW_WORKFLOW.actions, [edge(TRIGGER_NODE_ID, EXIT_NODE_ID, 'continue')])
            logic.actions.startPlacingNewStep(CLASSIFY_ACTION_NODE)

            cancel()

            expect(addedActions()).toEqual([])
            expect(logic.values.isPlacingNewStep).toBe(false)
            expect(logic.values.nodeToBeAdded).toBeNull()
            expect(logic.values.dropzoneNodes).toEqual([])
            expect(capturedEvent('workflow step placement finished')).toEqual([
                { step_id: 'template-posthog-classify', outcome: 'cancelled' },
            ])
        })

        const linearWithDelay = {
            actions: [NEW_WORKFLOW.actions[0], delay, NEW_WORKFLOW.actions[1]],
            edges: [edge(TRIGGER_NODE_ID, delay.id, 'continue'), edge(delay.id, EXIT_NODE_ID, 'continue')],
        }
        const delayNode = (): HogFlowActionNode => logic.values.nodesById[delay.id]
        const newDelayStep: CreateActionType = DELAY_NODES_TO_SHOW[0]

        it.each([
            { name: 'copy', start: () => logic.actions.startCopyingNode(delayNode()) },
            { name: 'move', start: () => logic.actions.startMovingNode(delayNode()) },
        ])('ends a pending $name when placement starts, and places the picked step', async ({ start }) => {
            await setWorkflow(linearWithDelay.actions, linearWithDelay.edges)
            start()

            logic.actions.startPlacingNewStep(CLASSIFY_ACTION_NODE)

            expect(logic.values.isCopyingNode).toBe(false)
            expect(logic.values.isMovingNode).toBe(false)
            logic.actions.placeNewStep(edge(delay.id, EXIT_NODE_ID, 'continue'))
            const [added] = addedActions()
            expect(added).toMatchObject({ config: { template_id: 'template-posthog-classify' } })
            expect(logic.values.workflow.edges).toEqual([
                edge(TRIGGER_NODE_ID, delay.id, 'continue'),
                edge(delay.id, added.id, 'continue'),
                edge(added.id, EXIT_NODE_ID, 'continue'),
            ])
        })

        it.each([
            {
                name: 'copying a step',
                start: () => logic.actions.startCopyingNode(delayNode()),
                expectedNodeToBeAdded: () => delayNode().data,
            },
            {
                name: 'moving a step',
                start: () => logic.actions.startMovingNode(delayNode()),
                expectedNodeToBeAdded: () => null,
            },
            {
                name: 'duplicating a step',
                start: () => logic.actions.duplicateNodeBelow(delay.id),
                expectedNodeToBeAdded: () => null,
            },
        ])('cancels a pending placement when $name starts', async ({ start, expectedNodeToBeAdded }) => {
            await setWorkflow(linearWithDelay.actions, linearWithDelay.edges)
            logic.actions.startPlacingNewStep(CLASSIFY_ACTION_NODE)

            start()

            expect(logic.values.isPlacingNewStep).toBe(false)
            expect(logic.values.nodeToBeAdded).toEqual(expectedNodeToBeAdded())
            expect(addedActions().filter((action) => action.type === 'function')).toEqual([])
            expect(capturedEvent('workflow step placement finished')).toEqual([
                { step_id: 'template-posthog-classify', outcome: 'cancelled' },
            ])
        })

        it.each([
            {
                name: 'is dragged in',
                add: () => {
                    logic.actions.setNodeToBeAdded(newDelayStep)
                    logic.actions.onDrop(undefined, edge(delay.id, EXIT_NODE_ID, 'continue'))
                },
                expected: [{ action_type: 'delay', template_id: null, step_picker_enabled: true }],
            },
            {
                name: 'is placed from the step picker',
                add: () => {
                    logic.actions.startPlacingNewStep(CLASSIFY_ACTION_NODE)
                    logic.actions.placeNewStep(edge(delay.id, EXIT_NODE_ID, 'continue'))
                },
                expected: [
                    {
                        action_type: 'function',
                        template_id: 'template-posthog-classify',
                        step_picker_enabled: true,
                    },
                ],
            },
            {
                name: 'is copied',
                add: () => {
                    logic.actions.startCopyingNode(delayNode())
                    highlightDropzone(delay.id, EXIT_NODE_ID, false)
                    logic.actions.copyNodeToHighlightedDropzone()
                },
                expected: [],
            },
            {
                name: 'is moved',
                add: () => logic.actions.moveNodeToEdge(delay.id, edge(TRIGGER_NODE_ID, delay.id, 'continue'), false),
                expected: [],
            },
            {
                name: 'is duplicated',
                add: () => logic.actions.duplicateNodeBelow(delay.id),
                expected: [],
            },
        ])('captures workflow step added only when a new step $name', async ({ add, expected }) => {
            await setWorkflow(linearWithDelay.actions, linearWithDelay.edges)

            add()

            expect(capturedEvent('workflow step added')).toEqual(expected)
        })
    })

    describe('showDropzones branch-join placement', () => {
        const makeNode = (id: string): HogFlowActionNode =>
            ({
                id,
                type: 'action',
                data: { id, type: 'exit', name: id, description: '', config: {} } as unknown as HogFlowAction,
                position: { x: 0, y: 0 },
                handles: [],
            }) as HogFlowActionNode

        const makeEdge = (
            from: string,
            to: string,
            type: 'continue' | 'branch',
            index?: number
        ): HogFlowActionEdge => ({
            id: `${from}->${to} ${type} ${index ?? ''}`.trim(),
            source: from,
            target: to,
            type: 'smart',
            sourceHandle: type === 'continue' ? `continue_${from}` : `branch_${from}_${index}`,
            targetHandle: `target_${to}`,
            data: { edge: { from, to, type, index } },
        })

        const branchJoinDropzones = (): { id: string; targetId: string }[] =>
            logic.values.dropzoneNodes
                .filter((n) => n.data.isBranchJoinDropzone)
                .map((n) => ({ id: n.id, targetId: n.data.edge.target as string }))

        it.each([
            {
                name: 'branches are empty (regression)',
                nodes: ['trigger', 'cond', 'exit'],
                edges: [
                    makeEdge('trigger', 'cond', 'continue'),
                    makeEdge('cond', 'exit', 'branch', 0),
                    makeEdge('cond', 'exit', 'branch', 1),
                    makeEdge('cond', 'exit', 'continue'),
                ],
                expected: [{ id: 'dropzone_target_exit_branch_join', targetId: 'exit' }],
            },
            {
                name: 'branches are populated',
                nodes: ['trigger', 'cond', 'email1', 'email2', 'exit'],
                edges: [
                    makeEdge('trigger', 'cond', 'continue'),
                    makeEdge('cond', 'email1', 'branch', 0),
                    makeEdge('cond', 'email2', 'branch', 1),
                    makeEdge('cond', 'exit', 'continue'),
                    makeEdge('email1', 'exit', 'continue'),
                    makeEdge('email2', 'exit', 'continue'),
                ],
                expected: [{ id: 'dropzone_target_exit_branch_join', targetId: 'exit' }],
            },
            {
                name: 'purely linear chain - no dropzone',
                nodes: ['trigger', 'a', 'exit'],
                edges: [makeEdge('trigger', 'a', 'continue'), makeEdge('a', 'exit', 'continue')],
                expected: [],
            },
        ])('shows correct branch-join dropzones when $name', ({ nodes, edges, expected }) => {
            logic.actions.setNodesRaw(nodes.map(makeNode))
            logic.actions.setEdges(edges)
            logic.actions.showDropzones()
            expect(branchJoinDropzones()).toEqual(expected)
        })
    })
})
