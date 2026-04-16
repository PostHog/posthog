import {
    getBranchRemovalDisabledReason,
    removeBranchEdge,
    updateItemWithOptionalName,
    updateOptionalName,
} from './utils'

describe('utils', () => {
    describe('updateOptionalName', () => {
        it('should add name when value is provided', () => {
            const obj = { id: '1', filters: {} }
            const result = updateOptionalName(obj, 'Custom Name')

            expect(result).toEqual({
                id: '1',
                filters: {},
                name: 'Custom Name',
            })
        })

        it('should update existing name when new value is provided', () => {
            const obj = { id: '1', filters: {}, name: 'Old Name' }
            const result = updateOptionalName(obj, 'New Name')

            expect(result).toEqual({
                id: '1',
                filters: {},
                name: 'New Name',
            })
        })

        it('should remove name when value is empty string', () => {
            const obj = { id: '1', filters: {}, name: 'Existing Name' }
            const result = updateOptionalName(obj, '')

            expect(result).toEqual({
                id: '1',
                filters: {},
            })
            expect('name' in result).toBe(false)
        })

        it('should remove name when value is undefined', () => {
            const obj = { id: '1', filters: {}, name: 'Existing Name' }
            const result = updateOptionalName(obj, undefined)

            expect(result).toEqual({
                id: '1',
                filters: {},
            })
            expect('name' in result).toBe(false)
        })

        it('should preserve other properties', () => {
            const obj = {
                id: '1',
                filters: { test: true },
                otherProp: 'value',
                nested: { deep: 'object' },
            }
            const result = updateOptionalName(obj, 'Name')

            expect(result).toEqual({
                id: '1',
                filters: { test: true },
                otherProp: 'value',
                nested: { deep: 'object' },
                name: 'Name',
            })
        })
    })

    describe('getBranchRemovalDisabledReason', () => {
        interface TestEdge {
            from: string
            to: string
            type: 'branch' | 'continue'
            index?: number
        }

        const edge = (from: string, to: string, type: 'branch' | 'continue', index?: number): TestEdge => ({
            from,
            to,
            type,
            index,
        })

        function buildEdgesByActionId(edges: TestEdge[]): Record<string, TestEdge[]> {
            return edges.reduce(
                (acc, e) => {
                    if (!acc[e.from]) {
                        acc[e.from] = []
                    }
                    acc[e.from].push(e)
                    if (!acc[e.to]) {
                        acc[e.to] = []
                    }
                    acc[e.to].push(e)
                    return acc
                },
                {} as Record<string, TestEdge[]>
            )
        }

        it('should allow removal when no branch edge exists for the condition', () => {
            const branchEdges: TestEdge[] = []
            const edgesByActionId = buildEdgesByActionId([])
            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBeUndefined()
        })

        it('should allow removal when branch target has other incoming edges', () => {
            const branchEdge = edge('cond', 'exit', 'branch', 0)
            const continueEdge = edge('webhook', 'exit', 'continue')
            const branchEdges = [branchEdge]
            const edgesByActionId = buildEdgesByActionId([branchEdge, continueEdge])

            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBeUndefined()
        })

        it('should block removal when branch target would be orphaned', () => {
            const branchEdge = edge('cond', 'webhook', 'branch', 0)
            const branchEdges = [branchEdge]
            const edgesByActionId = buildEdgesByActionId([branchEdge])

            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBe(
                'Clean up branching steps first'
            )
        })

        it('should allow removal when branch points to same node as continue edge', () => {
            const branchEdge = edge('cond', 'exit', 'branch', 0)
            const continueEdge = edge('cond', 'exit', 'continue')
            const branchEdges = [branchEdge]
            const edgesByActionId = buildEdgesByActionId([branchEdge, continueEdge])

            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBeUndefined()
        })

        it('should match by edge index property, not array position', () => {
            const branchEdge1 = edge('cond', 'webhook', 'branch', 1)
            const branchEdge2 = edge('cond', 'exit', 'branch', 2)
            const otherEdgeToExit = edge('webhook', 'exit', 'continue')
            const branchEdges = [branchEdge1, branchEdge2]
            const edgesByActionId = buildEdgesByActionId([branchEdge1, branchEdge2, otherEdgeToExit])

            // Index 0 has no branch edge
            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBeUndefined()
            // Index 1 points to webhook (only incoming edge) — blocked
            expect(getBranchRemovalDisabledReason(branchEdges, 1, edgesByActionId)).toBe(
                'Clean up branching steps first'
            )
            // Index 2 points to exit (has other incoming edge from webhook) — allowed
            expect(getBranchRemovalDisabledReason(branchEdges, 2, edgesByActionId)).toBeUndefined()
        })

        it('should handle multiple branches pointing to the same target', () => {
            const branchEdge0 = edge('cond', 'webhook', 'branch', 0)
            const branchEdge1 = edge('cond', 'webhook', 'branch', 1)
            const branchEdges = [branchEdge0, branchEdge1]
            const edgesByActionId = buildEdgesByActionId([branchEdge0, branchEdge1])

            // Each branch has the other as an additional incoming edge to the target
            expect(getBranchRemovalDisabledReason(branchEdges, 0, edgesByActionId)).toBeUndefined()
            expect(getBranchRemovalDisabledReason(branchEdges, 1, edgesByActionId)).toBeUndefined()
        })
    })

    describe('removeBranchEdge', () => {
        it('should remove the edge with the matching index and reindex', () => {
            const edges = [
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'c', type: 'branch', index: 1 },
                { from: 'a', to: 'd', type: 'branch', index: 2 },
            ]
            const result = removeBranchEdge(edges, 1)

            expect(result).toEqual([
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'd', type: 'branch', index: 1 },
            ])
        })

        it('should return all edges reindexed when removing index 0', () => {
            const edges = [
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'c', type: 'branch', index: 1 },
            ]
            const result = removeBranchEdge(edges, 0)

            expect(result).toEqual([{ from: 'a', to: 'c', type: 'branch', index: 0 }])
        })

        it('should return empty array when removing the only edge', () => {
            const edges = [{ from: 'a', to: 'b', type: 'branch', index: 0 }]
            const result = removeBranchEdge(edges, 0)

            expect(result).toEqual([])
        })

        it('should return all edges unchanged when index does not match', () => {
            const edges = [
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'c', type: 'branch', index: 1 },
            ]
            const result = removeBranchEdge(edges, 5)

            expect(result).toEqual([
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'c', type: 'branch', index: 1 },
            ])
        })

        it('should return new array (immutability)', () => {
            const edges = [
                { from: 'a', to: 'b', type: 'branch', index: 0 },
                { from: 'a', to: 'c', type: 'branch', index: 1 },
            ]
            const result = removeBranchEdge(edges, 1)

            expect(result).not.toBe(edges)
        })
    })

    describe('updateItemWithOptionalName', () => {
        it('should update name at specified index', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
                { id: '3', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 1, 'Middle Item')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {}, name: 'Middle Item' },
                { id: '3', filters: {} },
            ])
        })

        it('should remove name at specified index when value is empty', () => {
            const items = [
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {}, name: 'Second' },
                { id: '3', filters: {}, name: 'Third' },
            ]
            const result = updateItemWithOptionalName(items, 1, '')

            expect(result).toEqual([
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {} },
                { id: '3', filters: {}, name: 'Third' },
            ])
            expect('name' in result[1]).toBe(false)
        })

        it('should only modify the item at the specified index', () => {
            const items = [
                { id: '1', filters: {}, name: 'First' },
                { id: '2', filters: {} },
                { id: '3', filters: {}, name: 'Third' },
            ]
            const result = updateItemWithOptionalName(items, 1, 'Second')

            expect(result[0]).toEqual({ id: '1', filters: {}, name: 'First' })
            expect(result[1]).toEqual({ id: '2', filters: {}, name: 'Second' })
            expect(result[2]).toEqual({ id: '3', filters: {}, name: 'Third' })
        })

        it('should handle index out of bounds gracefully', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 5, 'Out of bounds')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ])
        })

        it('should handle negative index gracefully', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, -1, 'Negative')

            expect(result).toEqual([
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ])
        })

        it('should return a new array (immutability)', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 0, 'First')

            expect(result).not.toBe(items)
            expect(items[0]).toEqual({ id: '1', filters: {} }) // Original unchanged
        })

        it('should return new objects for modified items (deep immutability)', () => {
            const items = [
                { id: '1', filters: {} },
                { id: '2', filters: {} },
            ]
            const result = updateItemWithOptionalName(items, 0, 'First')

            expect(result[0]).not.toBe(items[0]) // Modified item is new
            expect(result[1]).toBe(items[1]) // Unmodified item is same reference
        })

        it('should handle empty array', () => {
            const items: Array<{ filters: {}; name?: string }> = []
            const result = updateItemWithOptionalName(items, 0, 'Name')

            expect(result).toEqual([])
        })
    })
})
