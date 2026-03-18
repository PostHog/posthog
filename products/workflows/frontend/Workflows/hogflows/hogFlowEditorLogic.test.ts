import { initKeaTests } from '~/test/init'

import { computeMoveEdges, hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlow, HogFlowAction } from './types'

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
})
