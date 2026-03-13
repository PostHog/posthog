import type { HogFlowAction, HogFlowEdge } from './hogflows/types'
import { stripDeletedActions } from './workflowLogic'

function makeAction(id: string, type: string = 'function'): HogFlowAction {
    return { id, type, name: id, config: {}, created_at: 0, updated_at: 0 } as HogFlowAction
}

function makeEdge(from: string, to: string, type: string = 'continue'): HogFlowEdge {
    return { from, to, type } as HogFlowEdge
}

describe('stripDeletedActions', () => {
    it('removes a single linear node and re-wires edges', () => {
        // trigger -> A -> B -> exit
        const actions = [makeAction('trigger', 'trigger'), makeAction('A'), makeAction('B'), makeAction('exit', 'exit')]
        const edges = [makeEdge('trigger', 'A'), makeEdge('A', 'B'), makeEdge('B', 'exit')]

        const result = stripDeletedActions(actions, edges, new Set(['A']))

        expect(result.actions.map((a) => a.id)).toEqual(['trigger', 'B', 'exit'])
        expect(result.edges).toEqual([makeEdge('trigger', 'B'), makeEdge('B', 'exit')])
    })

    it('removes multiple linear nodes', () => {
        // trigger -> A -> B -> C -> exit
        const actions = [
            makeAction('trigger', 'trigger'),
            makeAction('A'),
            makeAction('B'),
            makeAction('C'),
            makeAction('exit', 'exit'),
        ]
        const edges = [makeEdge('trigger', 'A'), makeEdge('A', 'B'), makeEdge('B', 'C'), makeEdge('C', 'exit')]

        const result = stripDeletedActions(actions, edges, new Set(['A', 'C']))

        expect(result.actions.map((a) => a.id)).toEqual(['trigger', 'B', 'exit'])
        expect(result.edges).toEqual([makeEdge('trigger', 'B'), makeEdge('B', 'exit')])
    })

    it('processes leaf nodes before branching parents', () => {
        // branch -> child1 -> exit
        //        -> child2 -> exit
        // Deleting branch + child1 + child2: leaves first, then parent
        const actions = [
            makeAction('trigger', 'trigger'),
            makeAction('branch', 'conditional_branch'),
            makeAction('child1'),
            makeAction('child2'),
            makeAction('exit', 'exit'),
        ]
        const edges = [
            makeEdge('trigger', 'branch'),
            makeEdge('branch', 'child1', 'continue'),
            makeEdge('branch', 'child2', 'branch'),
            makeEdge('child1', 'exit'),
            makeEdge('child2', 'exit'),
        ]

        const result = stripDeletedActions(actions, edges, new Set(['child1', 'child2', 'branch']))

        expect(result.actions.map((a) => a.id)).toEqual(['trigger', 'exit'])
        expect(result.edges).toEqual([makeEdge('trigger', 'exit')])
    })

    it('returns unchanged arrays when deletedIds is empty', () => {
        const actions = [makeAction('trigger', 'trigger'), makeAction('A')]
        const edges = [makeEdge('trigger', 'A')]

        const result = stripDeletedActions(actions, edges, new Set())

        expect(result.actions).toEqual(actions)
        expect(result.edges).toEqual(edges)
    })

    it('removes a node with no outgoing continue edge by dropping all related edges', () => {
        // trigger -> A (no outgoing)
        const actions = [makeAction('trigger', 'trigger'), makeAction('A')]
        const edges = [makeEdge('trigger', 'A')]

        const result = stripDeletedActions(actions, edges, new Set(['A']))

        expect(result.actions.map((a) => a.id)).toEqual(['trigger'])
        expect(result.edges).toEqual([])
    })
})
