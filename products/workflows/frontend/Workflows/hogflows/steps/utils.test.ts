import {
    cohortPercentagesAddUp,
    getBranchRemovalDisabledReason,
    isCountableCondition,
    normalizeCohortPercentages,
    parseCohortPercentage,
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

        it.each(
            [
                () => ({
                    name: 'allows removal when no branch edge exists for the condition',
                    branchEdges: [] as TestEdge[],
                    allEdges: [] as TestEdge[],
                    expected: undefined,
                }),
                () => {
                    const branchEdge = edge('cond', 'exit', 'branch', 0)
                    return {
                        name: 'allows removal when branch target has other incoming edges',
                        branchEdges: [branchEdge],
                        allEdges: [branchEdge, edge('webhook', 'exit', 'continue')],
                        expected: undefined,
                    }
                },
                () => {
                    const branchEdge = edge('cond', 'webhook', 'branch', 0)
                    return {
                        name: 'blocks removal when branch target would be orphaned',
                        branchEdges: [branchEdge],
                        allEdges: [branchEdge],
                        expected: 'Clean up branching steps first',
                    }
                },
                () => {
                    const branchEdge = edge('cond', 'exit', 'branch', 0)
                    return {
                        name: 'allows removal when branch points to same node as continue edge',
                        branchEdges: [branchEdge],
                        allEdges: [branchEdge, edge('cond', 'exit', 'continue')],
                        expected: undefined,
                    }
                },
            ].map((f) => f())
        )('$name', ({ branchEdges, allEdges, expected }) => {
            expect(getBranchRemovalDisabledReason(branchEdges, 0, buildEdgesByActionId(allEdges))).toBe(expected)
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
        const e = (to: string, index: number): { from: string; to: string; type: 'branch'; index: number } => ({
            from: 'a',
            to,
            type: 'branch',
            index,
        })

        it.each([
            {
                name: 'removes the edge with the matching index and reindexes',
                edges: [e('b', 0), e('c', 1), e('d', 2)],
                indexToRemove: 1,
                expected: [e('b', 0), e('d', 1)],
            },
            {
                name: 'returns all edges reindexed when removing index 0',
                edges: [e('b', 0), e('c', 1)],
                indexToRemove: 0,
                expected: [e('c', 0)],
            },
            {
                name: 'returns empty array when removing the only edge',
                edges: [e('b', 0)],
                indexToRemove: 0,
                expected: [],
            },
            {
                name: 'returns all edges unchanged when index does not match',
                edges: [e('b', 0), e('c', 1)],
                indexToRemove: 5,
                expected: [e('b', 0), e('c', 1)],
            },
        ])('$name', ({ edges, indexToRemove, expected }) => {
            expect(removeBranchEdge(edges, indexToRemove)).toEqual(expected)
        })

        it('should return new array (immutability)', () => {
            const edges = [e('b', 0), e('c', 1)]
            const result = removeBranchEdge(edges, 1)

            expect(result).not.toBe(edges)
        })
    })

    describe('normalizeCohortPercentages', () => {
        it.each([
            { name: 'splits evenly when the count divides 100', count: 4, expected: [25, 25, 25, 25] },
            {
                name: 'uses a fractional share when whole percents cannot divide 100',
                count: 8,
                expected: [12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5, 12.5],
            },
            {
                name: 'spreads the leftover hundredths across the leading cohorts',
                count: 3,
                expected: [33.34, 33.33, 33.33],
            },
            { name: 'returns nothing when there are no cohorts', count: 0, expected: [] },
        ])('$name', ({ count, expected }) => {
            expect(normalizeCohortPercentages(count)).toEqual(expected)
        })

        // Allocating in whole percents summed to 100 too, but unevenly: 30 cohorts came out as ten
        // shares of 4% and twenty of 3%, so a third of the branches took 33% more traffic than the
        // rest. Asserting the total alone would not have caught that, hence the per-share bound.
        it.each([2, 3, 7, 8, 30, 99])('gives %i cohorts an equal share totalling 100', (count) => {
            const percentages = normalizeCohortPercentages(count)
            const total = percentages.reduce((sum, percentage) => sum + percentage, 0)

            expect(percentages).toHaveLength(count)
            expect(total).toBeCloseTo(100, 6)
            for (const percentage of percentages) {
                expect(Math.abs(percentage - 100 / count)).toBeLessThanOrEqual(0.01)
            }
        })
    })

    describe('cohortPercentagesAddUp', () => {
        // Both directions of this have bitten: comparing against 100 exactly reports the balance
        // button's own output as unbalanced, while a tolerance wide enough to cover a hundredth of a
        // percent hides shortfalls the runtime really does reroute to the last cohort.
        it.each([2, 3, 7, 8, 30, 99])('accepts the even split produced for %i cohorts', (count) => {
            expect(cohortPercentagesAddUp(normalizeCohortPercentages(count))).toBe(true)
        })

        it.each([
            { name: 'accepts shares totalling exactly 100', percentages: [50, 50], expected: true },
            {
                name: 'rejects a shortfall smaller than a hundredth of a percent',
                percentages: [50, 49.996],
                expected: false,
            },
            { name: 'rejects a whole-percent shortfall', percentages: [30, 30, 30], expected: false },
            { name: 'rejects an excess', percentages: [60, 60], expected: false },
            { name: 'rejects no shares at all', percentages: [], expected: false },
        ])('$name', ({ percentages, expected }) => {
            expect(cohortPercentagesAddUp(percentages)).toBe(expected)
        })
    })

    describe('parseCohortPercentage', () => {
        // A number field accepts more than plain decimals, and its max attribute only gates form
        // validation, which this input is not wired to. Without the clamp, "1e5" stores 100000 and
        // every cohort after the first becomes unreachable.
        it.each([
            { name: 'keeps a fractional share', value: '3.3', expected: 3.3 },
            { name: 'keeps a whole share', value: '50', expected: 50 },
            { name: 'clamps scientific notation over the maximum', value: '1e5', expected: 100 },
            { name: 'clamps a value over the maximum', value: '500', expected: 100 },
            { name: 'clamps a negative value up to zero', value: '-5', expected: 0 },
            { name: 'reads empty text as zero', value: '', expected: 0 },
            { name: 'reads unparseable text as zero', value: 'abc', expected: 0 },
        ])('$name', ({ value, expected }) => {
            expect(parseCohortPercentage(value)).toBe(expected)
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

    describe('isCountableCondition', () => {
        it.each([
            {
                case: 'person properties only',
                properties: [{ type: 'person', key: 'plan', value: 'free' }],
                expected: true,
            },
            { case: 'a cohort reference', properties: [{ type: 'cohort', key: 'id', value: 42 }], expected: true },
            {
                case: 'person and cohort mixed',
                properties: [
                    { type: 'person', key: 'plan' },
                    { type: 'cohort', key: 'id' },
                ],
                expected: true,
            },
            // An event property is evaluated against the triggering event, so counting persons would
            // report a percentage that answers a different question than the one asked.
            { case: 'an event property', properties: [{ type: 'event', key: '$current_url' }], expected: false },
            {
                case: 'a person property alongside an event property',
                properties: [{ type: 'person' }, { type: 'event' }],
                expected: false,
            },
            {
                case: 'a group property',
                properties: [{ type: 'group', key: 'name', group_type_index: 0 }],
                expected: false,
            },
            { case: 'a feature flag property', properties: [{ type: 'feature', key: 'my-flag' }], expected: false },
            {
                case: 'a HogQL expression',
                properties: [{ type: 'hogql', key: "properties.plan = 'free'" }],
                expected: false,
            },
            { case: 'an empty property row', properties: [{}], expected: false },
            { case: 'no properties', properties: [], expected: false },
        ])('$case -> $expected', ({ properties, expected }) => {
            expect(isCountableCondition({ properties })).toBe(expected)
        })

        it.each([[undefined], [null], [{}]])('returns false for missing filters (%s)', (filters) => {
            expect(isCountableCondition(filters)).toBe(false)
        })
    })
})
