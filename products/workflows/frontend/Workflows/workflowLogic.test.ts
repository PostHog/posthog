import { HogFlow, HogFlowAction } from './hogflows/types'
import { buildDraftData, configsEqual, hydrateDeletedActionIds, stripDeletedActions } from './workflowLogic'

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

const mockWorkflow = (draft?: Record<string, unknown> | null): HogFlow =>
    ({
        id: 'flow-1',
        name: 'Test',
        status: 'active',
        actions: [action('trigger', 'trigger'), action('A'), action('exit', 'exit')],
        edges: [edge('trigger', 'A', 'continue'), edge('A', 'exit', 'continue')],
        draft: draft ?? null,
    }) as unknown as HogFlow

describe('hydrateDeletedActionIds', () => {
    it.each([
        {
            name: 'extracts deleted IDs from draft',
            draft: { deleted_action_ids: ['A', 'B'] },
            expected: new Set(['A', 'B']),
        },
        {
            name: 'returns empty set when draft is null',
            draft: null,
            expected: new Set<string>(),
        },
        {
            name: 'returns empty set when draft has no deleted_action_ids',
            draft: { name: 'Draft Name' },
            expected: new Set<string>(),
        },
        {
            name: 'returns empty set when deleted_action_ids is not an array',
            draft: { deleted_action_ids: 'not-an-array' },
            expected: new Set<string>(),
        },
        {
            name: 'returns empty set for null workflow',
            draft: undefined,
            expected: new Set<string>(),
        },
    ])('$name', ({ draft, expected }) => {
        const workflow = draft === undefined ? null : mockWorkflow(draft)
        expect(hydrateDeletedActionIds(workflow)).toEqual(expected)
    })
})

describe('buildDraftData', () => {
    it('copies content fields from workflow', () => {
        const workflow = mockWorkflow()
        const result = buildDraftData(workflow)

        expect(result.name).toBe('Test')
        expect(result.actions).toBe(workflow.actions)
        expect(result.edges).toBe(workflow.edges)
        expect((result as any).id).toBeUndefined()
        expect((result as any).status).toBeUndefined()
        expect((result as any).draft).toBeUndefined()
    })

    it('includes deleted_action_ids when provided', () => {
        const workflow = mockWorkflow()
        const result = buildDraftData(workflow, new Set(['A', 'B']))

        expect((result as any).deleted_action_ids).toEqual(['A', 'B'])
    })

    it('omits deleted_action_ids when set is empty', () => {
        const workflow = mockWorkflow()
        const result = buildDraftData(workflow, new Set())

        expect((result as any).deleted_action_ids).toBeUndefined()
    })

    it('omits deleted_action_ids when not provided', () => {
        const workflow = mockWorkflow()
        const result = buildDraftData(workflow)

        expect((result as any).deleted_action_ids).toBeUndefined()
    })
})

describe('configsEqual', () => {
    it.each([
        {
            name: 'identical simple objects',
            a: { foo: 'bar', num: 1 },
            b: { foo: 'bar', num: 1 },
            expected: true,
        },
        {
            name: 'different key order is treated as equal',
            a: { z: 1, a: 2 },
            b: { a: 2, z: 1 },
            expected: true,
        },
        {
            name: 'different values are not equal',
            a: { foo: 'bar' },
            b: { foo: 'baz' },
            expected: false,
        },
        {
            name: 'bytecode key is ignored',
            a: { name: 'step', bytecode: [1, 2, 3] },
            b: { name: 'step' },
            expected: true,
        },
        {
            name: 'order key is ignored',
            a: { name: 'step', order: 5 },
            b: { name: 'step', order: 99 },
            expected: true,
        },
        {
            name: 'null vs missing treated as equal',
            a: { name: 'step', extra: null },
            b: { name: 'step' },
            expected: true,
        },
        {
            name: 'empty string vs missing treated as equal',
            a: { name: 'step', desc: '' },
            b: { name: 'step' },
            expected: true,
        },
        {
            name: 'false vs missing treated as equal',
            a: { name: 'step', enabled: false },
            b: { name: 'step' },
            expected: true,
        },
        {
            name: 'empty array vs missing treated as equal',
            a: { name: 'step', tags: [] },
            b: { name: 'step' },
            expected: true,
        },
        {
            name: 'non-empty array vs missing is not equal',
            a: { name: 'step', tags: ['a'] },
            b: { name: 'step' },
            expected: false,
        },
        {
            name: 'nested objects with different key order',
            a: { config: { z: 1, a: { y: 2, x: 3 } } },
            b: { config: { a: { x: 3, y: 2 }, z: 1 } },
            expected: true,
        },
        {
            name: 'nested objects with server keys stripped at depth',
            a: { config: { name: 'x', bytecode: [1] } },
            b: { config: { name: 'x' } },
            expected: true,
        },
        {
            name: 'arrays preserve element order',
            a: { items: [1, 2, 3] },
            b: { items: [3, 2, 1] },
            expected: false,
        },
        {
            name: 'arrays with nested objects normalized',
            a: { items: [{ b: 1, a: 2 }] },
            b: { items: [{ a: 2, b: 1 }] },
            expected: true,
        },
        {
            name: 'primitive values compared directly',
            a: 42,
            b: 42,
            expected: true,
        },
        {
            name: 'different primitives are not equal',
            a: 'hello',
            b: 'world',
            expected: false,
        },
        {
            name: 'undefined vs missing in nested object treated as equal',
            a: { config: { name: 'x', value: undefined } },
            b: { config: { name: 'x' } },
            expected: true,
        },
    ])('$name', ({ a, b, expected }) => {
        expect(configsEqual(a, b)).toBe(expected)
    })
})
