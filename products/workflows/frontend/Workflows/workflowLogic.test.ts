import { HogFlow, HogFlowAction } from './hogflows/types'
import { stripDeletedActions } from './workflowLogic'

type Edge = HogFlow['edges'][0]
const edge = (from: string, to: string, type: 'continue' | 'branch', index?: number): Edge => ({
    from,
    to,
    type,
    index,
})

const action = (id: string, type: string = 'function'): HogFlowAction =>
    ({
        id,
        type,
        name: id,
        description: '',
        config: {},
        created_at: 0,
        updated_at: 0,
    }) as unknown as HogFlowAction

describe('stripDeletedActions', () => {
    it.each([
        {
            name: 'single node in linear chain',
            actions: [action('trigger', 'trigger'), action('A'), action('exit', 'exit')],
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')],
            deletedIds: new Set(['A']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'middle node in chain of three',
            actions: [action('trigger', 'trigger'), action('A'), action('B'), action('C'), action('exit', 'exit')],
            edges: [
                edge('trigger', 'A', 'continue'),
                edge('A', 'B', 'continue'),
                edge('B', 'C', 'continue'),
                edge('C', 'exit', 'continue'),
            ],
            deletedIds: new Set(['B']),
            expectedActions: ['trigger', 'A', 'C', 'exit'],
            expectedEdges: [
                edge('trigger', 'A', 'continue'),
                edge('A', 'C', 'continue'),
                edge('C', 'exit', 'continue'),
            ],
        },
        {
            name: 'two consecutive nodes deleted',
            actions: [action('trigger', 'trigger'), action('A'), action('B'), action('exit', 'exit')],
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'B', 'continue'), edge('B', 'exit', 'continue')],
            deletedIds: new Set(['A', 'B']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'conditional branch with children deleted first',
            actions: [
                action('trigger', 'trigger'),
                action('cond', 'conditional_branch'),
                action('branchA'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'branchA', 'branch', 0),
                edge('cond', 'exit', 'continue'),
                edge('branchA', 'exit', 'continue'),
            ],
            deletedIds: new Set(['branchA', 'cond']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'only branch child deleted, branching node kept',
            actions: [
                action('trigger', 'trigger'),
                action('cond', 'conditional_branch'),
                action('branchA'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'branchA', 'branch', 0),
                edge('cond', 'exit', 'continue'),
                edge('branchA', 'exit', 'continue'),
            ],
            deletedIds: new Set(['branchA']),
            expectedActions: ['trigger', 'cond', 'exit'],
            expectedEdges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'exit', 'branch', 0),
                edge('cond', 'exit', 'continue'),
            ],
        },
        {
            name: 'conditional branch with two children, both deleted then branch deleted',
            actions: [
                action('trigger', 'trigger'),
                action('cond', 'conditional_branch'),
                action('branchA'),
                action('branchB'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'branchA', 'branch', 0),
                edge('cond', 'branchB', 'branch', 1),
                edge('cond', 'exit', 'continue'),
                edge('branchA', 'exit', 'continue'),
                edge('branchB', 'exit', 'continue'),
            ],
            deletedIds: new Set(['branchA', 'branchB', 'cond']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'empty deleted set returns unchanged data',
            actions: [action('trigger', 'trigger'), action('A'), action('exit', 'exit')],
            edges: [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')],
            deletedIds: new Set<string>(),
            expectedActions: ['trigger', 'A', 'exit'],
            expectedEdges: [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')],
        },
        {
            name: 'node without continue edge is removed without reconnection',
            actions: [action('trigger', 'trigger'), action('exit', 'exit'), action('orphan')],
            edges: [edge('trigger', 'exit', 'continue')],
            deletedIds: new Set(['orphan']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'deleted node at join point with multiple incoming edges',
            actions: [
                action('trigger', 'trigger'),
                action('cond', 'conditional_branch'),
                action('branchA'),
                action('branchB'),
                action('join'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'branchA', 'branch', 0),
                edge('cond', 'branchB', 'continue'),
                edge('branchA', 'join', 'continue'),
                edge('branchB', 'join', 'continue'),
                edge('join', 'exit', 'continue'),
            ],
            deletedIds: new Set(['join']),
            expectedActions: ['trigger', 'cond', 'branchA', 'branchB', 'exit'],
            expectedEdges: [
                edge('trigger', 'cond', 'continue'),
                edge('cond', 'branchA', 'branch', 0),
                edge('cond', 'branchB', 'continue'),
                edge('branchA', 'exit', 'continue'),
                edge('branchB', 'exit', 'continue'),
            ],
        },
        {
            name: 'chain: deleted node continues to another deleted node',
            actions: [action('trigger', 'trigger'), action('A'), action('B'), action('C'), action('exit', 'exit')],
            edges: [
                edge('trigger', 'A', 'continue'),
                edge('A', 'B', 'continue'),
                edge('B', 'C', 'continue'),
                edge('C', 'exit', 'continue'),
            ],
            deletedIds: new Set(['A', 'C']),
            expectedActions: ['trigger', 'B', 'exit'],
            expectedEdges: [edge('trigger', 'B', 'continue'), edge('B', 'exit', 'continue')],
        },
        {
            name: 'wait_until_condition treated as branching type and processed last',
            actions: [
                action('trigger', 'trigger'),
                action('wait', 'wait_until_condition'),
                action('matched'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'wait', 'continue'),
                edge('wait', 'matched', 'branch', 0),
                edge('wait', 'exit', 'continue'),
                edge('matched', 'exit', 'continue'),
            ],
            deletedIds: new Set(['matched', 'wait']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
        {
            name: 'random_cohort_branch treated as branching type and processed last',
            actions: [
                action('trigger', 'trigger'),
                action('cohort', 'random_cohort_branch'),
                action('groupA'),
                action('groupB'),
                action('exit', 'exit'),
            ],
            edges: [
                edge('trigger', 'cohort', 'continue'),
                edge('cohort', 'groupA', 'branch', 0),
                edge('cohort', 'groupB', 'branch', 1),
                edge('cohort', 'exit', 'continue'),
                edge('groupA', 'exit', 'continue'),
                edge('groupB', 'exit', 'continue'),
            ],
            deletedIds: new Set(['groupA', 'groupB', 'cohort']),
            expectedActions: ['trigger', 'exit'],
            expectedEdges: [edge('trigger', 'exit', 'continue')],
        },
    ])('$name', ({ actions, edges, deletedIds, expectedActions, expectedEdges }) => {
        const result = stripDeletedActions(actions, edges, deletedIds)
        expect(result.actions.map((a) => a.id)).toEqual(expectedActions)
        expect(result.edges).toEqual(expectedEdges)
    })

    it('does not mutate input arrays', () => {
        const actions = [action('trigger', 'trigger'), action('A'), action('exit', 'exit')]
        const edges = [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')]
        const originalActions = [...actions]
        const originalEdges = [...edges]

        stripDeletedActions(actions, edges, new Set(['A']))

        expect(actions).toEqual(originalActions)
        expect(edges).toEqual(originalEdges)
    })
})
