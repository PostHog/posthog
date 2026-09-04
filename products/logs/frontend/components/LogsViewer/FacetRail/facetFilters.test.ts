import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    FacetFilterTarget,
    SERVICE_NAME_FILTER,
    SEVERITY_LEVEL_FILTER,
    cycleFacetValue,
    facetFilterTarget,
    facetSelection,
    setFacetIncluded,
    setFacetSelection,
} from './facetFilters'
import type { FacetSource } from './facets'

const NAMESPACE: FacetFilterTarget = {
    key: 'k8s.namespace.name',
    type: PropertyFilterType.LogResourceAttribute,
}

const groupOf = (filters: Record<string, unknown>[]): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: filters as UniversalFiltersGroup['values'] }],
})

const filterOf = (target: FacetFilterTarget, operator: PropertyOperator, value: unknown): Record<string, unknown> => ({
    key: target.key,
    type: target.type,
    operator,
    value,
})

const innerValues = (group: UniversalFiltersGroup): unknown[] => (group.values[0] as UniversalFiltersGroup).values

describe('facetFilters', () => {
    describe('facetFilterTarget', () => {
        it.each<[string, FacetSource, FacetFilterTarget]>([
            [
                'a column facet stores its selection as a log filter under its logKey',
                { type: 'column', column: 'severity_text', logKey: 'severity_level' },
                {
                    key: 'severity_level',
                    type: PropertyFilterType.Log,
                },
            ],
            [
                'a resource-attribute facet stores its selection under its attribute key',
                { type: 'resourceAttribute', key: 'k8s.namespace.name' },
                NAMESPACE,
            ],
            [
                'a plain-attribute (custom) facet stores its selection as log_attribute, not log_resource_attribute',
                { type: 'attribute', key: 'log.iostream' },
                {
                    key: 'log.iostream',
                    type: PropertyFilterType.LogAttribute,
                },
            ],
        ])('%s', (_, source, expected) => {
            expect(facetFilterTarget(source)).toEqual(expected)
        })
    })

    describe('facetSelection', () => {
        it.each<[string, FacetFilterTarget, Record<string, unknown>[], string[], string[]]>([
            ['empty group reads as empty selection', NAMESPACE, [], [], []],
            [
                'exact array filter reads as included',
                NAMESPACE,
                [filterOf(NAMESPACE, PropertyOperator.Exact, ['a', 'b'])],
                ['a', 'b'],
                [],
            ],
            [
                'is_not array filter reads as excluded',
                NAMESPACE,
                [filterOf(NAMESPACE, PropertyOperator.IsNot, ['c'])],
                [],
                ['c'],
            ],
            [
                'both polarities read into their own sets',
                NAMESPACE,
                [
                    filterOf(NAMESPACE, PropertyOperator.Exact, ['a']),
                    filterOf(NAMESPACE, PropertyOperator.IsNot, ['c']),
                ],
                ['a'],
                ['c'],
            ],
            [
                'scalar chip value reads as a single-element set',
                NAMESPACE,
                [filterOf(NAMESPACE, PropertyOperator.Exact, 'a')],
                ['a'],
                [],
            ],
            [
                'other operators are not facet state',
                NAMESPACE,
                [filterOf(NAMESPACE, PropertyOperator.IContains, 'a')],
                [],
                [],
            ],
            [
                'other keys are not this facet',
                NAMESPACE,
                [filterOf({ key: 'host.name', type: NAMESPACE.type }, PropertyOperator.Exact, ['a'])],
                [],
                [],
            ],
            // The chips bar can hold any property type under a key, so the type has to discriminate:
            // a resource-attribute filter named severity_level filters an attribute, not the column.
            [
                'a resource-attribute filter under a column facet key is not that column selection',
                SEVERITY_LEVEL_FILTER,
                [
                    filterOf(
                        { key: 'severity_level', type: PropertyFilterType.LogResourceAttribute },
                        PropertyOperator.Exact,
                        ['error']
                    ),
                ],
                [],
                [],
            ],
            [
                'an exact log filter under a column facet key reads as that column selection',
                SEVERITY_LEVEL_FILTER,
                [filterOf(SEVERITY_LEVEL_FILTER, PropertyOperator.Exact, ['error'])],
                ['error'],
                [],
            ],
        ])('%s', (_, target, filters, included, excluded) => {
            expect(facetSelection(groupOf(filters), target)).toEqual({ included, excluded })
        })
    })

    describe('cycleFacetValue', () => {
        it.each<[string, FacetFilterTarget]>([
            ['a resource attribute', NAMESPACE],
            ['a column facet', SERVICE_NAME_FILTER],
        ])('cycles %s unchecked → included → excluded → unchecked', (_, target) => {
            const afterFirst = cycleFacetValue(groupOf([]), target, 'argocd')
            expect(facetSelection(afterFirst, target)).toEqual({ included: ['argocd'], excluded: [] })

            const afterSecond = cycleFacetValue(afterFirst, target, 'argocd')
            expect(facetSelection(afterSecond, target)).toEqual({ included: [], excluded: ['argocd'] })

            const afterThird = cycleFacetValue(afterSecond, target, 'argocd')
            expect(facetSelection(afterThird, target)).toEqual({ included: [], excluded: [] })
            // both filters are dropped once their side of the selection empties
            expect(innerValues(afterThird)).toEqual([])
        })

        it('writes includes as an exact filter and excludes as an is_not filter, both array-valued', () => {
            let group = cycleFacetValue(groupOf([]), NAMESPACE, 'a')
            group = cycleFacetValue(group, NAMESPACE, 'b')
            group = cycleFacetValue(group, NAMESPACE, 'a') // a → excluded

            expect(innerValues(group)).toEqual([
                filterOf(NAMESPACE, PropertyOperator.Exact, ['b']),
                filterOf(NAMESPACE, PropertyOperator.IsNot, ['a']),
            ])
        })

        it('preserves other keys and same-key non-facet chips when writing', () => {
            const otherKey = filterOf(
                { key: 'deployment.environment.name', type: NAMESPACE.type },
                PropertyOperator.Exact,
                ['prod']
            )
            const sameKeyContains = filterOf(NAMESPACE, PropertyOperator.IContains, 'kube')
            const group = cycleFacetValue(groupOf([otherKey, sameKeyContains]), NAMESPACE, 'argocd')

            expect(innerValues(group)).toEqual([
                otherKey,
                sameKeyContains,
                filterOf(NAMESPACE, PropertyOperator.Exact, ['argocd']),
            ])
        })

        // A user can edit an exclusion chip's operator to `=` in the filter bar, which leaves the same
        // value on both sides. Cycling out of that must land on one polarity, not AND the two together.
        it('a value in both polarities (hand-edited chips) cycles to excluded only, without duplication', () => {
            const corrupt = groupOf([
                filterOf(NAMESPACE, PropertyOperator.Exact, ['a']),
                filterOf(NAMESPACE, PropertyOperator.IsNot, ['a']),
            ])
            const cycled = cycleFacetValue(corrupt, NAMESPACE, 'a')
            expect(facetSelection(cycled, NAMESPACE)).toEqual({ included: [], excluded: ['a'] })
            expect(innerValues(cycled)).toEqual([filterOf(NAMESPACE, PropertyOperator.IsNot, ['a'])])
        })
    })

    // A log with no service_name facets as '', which the services table shows as "(no service)".
    it("reads back a '' service selection so its row can cycle", () => {
        const cycled = cycleFacetValue(groupOf([]), SERVICE_NAME_FILTER, '')

        expect(facetSelection(cycled, SERVICE_NAME_FILTER).included).toEqual([''])
    })

    describe('setFacetSelection', () => {
        it('keeps a sibling group the facet does not own', () => {
            const sibling = { type: FilterLogicalOperator.Or, values: [] } as UniversalFiltersGroup
            const group: UniversalFiltersGroup = {
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }, sibling],
            }

            const written = setFacetSelection(group, SERVICE_NAME_FILTER, { included: ['api'], excluded: [] })

            expect(written.values).toHaveLength(2)
            expect(written.values[1]).toEqual(sibling)
            expect(facetSelection(written, SERVICE_NAME_FILTER)).toEqual({ included: ['api'], excluded: [] })
        })
    })

    describe('setFacetIncluded', () => {
        it('replaces the included values and leaves the exclusions alone', () => {
            const group = groupOf([
                filterOf(SERVICE_NAME_FILTER, PropertyOperator.Exact, ['api']),
                filterOf(SERVICE_NAME_FILTER, PropertyOperator.IsNot, ['worker']),
            ])
            expect(
                facetSelection(setFacetIncluded(group, SERVICE_NAME_FILTER, ['batch']), SERVICE_NAME_FILTER)
            ).toEqual({ included: ['batch'], excluded: ['worker'] })
        })

        it('drops the exact filter when the included set empties', () => {
            const group = setFacetIncluded(groupOf([]), SERVICE_NAME_FILTER, ['api'])
            expect(innerValues(setFacetIncluded(group, SERVICE_NAME_FILTER, []))).toEqual([])
        })
    })
})
