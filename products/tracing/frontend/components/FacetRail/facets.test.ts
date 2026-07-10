import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { FilterGroupFacetSource, facetFilterValues, toggleFacetFilter } from './facets'

const STATUS_SOURCE: FilterGroupFacetSource = { type: 'column', column: 'status_code' }
const POD_SOURCE: FilterGroupFacetSource = { type: 'resourceAttribute', key: 'k8s.pod.name' }

function groupWith(values: object[]): UniversalFiltersGroup {
    return {
        type: FilterLogicalOperator.And,
        values: [{ type: FilterLogicalOperator.And, values: values as UniversalFiltersGroup['values'] }],
    }
}

describe('facets', () => {
    describe('toggleFacetFilter / facetFilterValues', () => {
        it.each<[string, FilterGroupFacetSource, PropertyFilterType]>([
            ['column facet writes a span filter', STATUS_SOURCE, PropertyFilterType.Span],
            [
                'resource-attribute facet writes a span_resource_attribute filter',
                POD_SOURCE,
                PropertyFilterType.SpanResourceAttribute,
            ],
        ])('%s', (_, source, expectedType) => {
            const group = toggleFacetFilter(undefined, source, 'a')
            const inner = (group.values[0] as UniversalFiltersGroup).values
            expect(inner).toEqual([
                expect.objectContaining({ type: expectedType, operator: PropertyOperator.Exact, value: ['a'] }),
            ])
            expect(facetFilterValues(group, source)).toEqual(['a'])
        })

        it('accumulates values on repeated toggles and removes on re-toggle', () => {
            let group = toggleFacetFilter(undefined, POD_SOURCE, 'pod-a')
            group = toggleFacetFilter(group, POD_SOURCE, 'pod-b')
            expect(facetFilterValues(group, POD_SOURCE)).toEqual(['pod-a', 'pod-b'])

            group = toggleFacetFilter(group, POD_SOURCE, 'pod-a')
            expect(facetFilterValues(group, POD_SOURCE)).toEqual(['pod-b'])
        })

        it('drops the filter entirely when the last value is toggled off', () => {
            const group = toggleFacetFilter(toggleFacetFilter(undefined, POD_SOURCE, 'pod-a'), POD_SOURCE, 'pod-a')
            expect((group.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('preserves unrelated filters, including a same-key filter of a different type', () => {
            // A span *attribute* also named k8s.pod.name must not be clobbered by the
            // resource-attribute facet — the two live in different filter types.
            const other = {
                key: 'k8s.pod.name',
                type: PropertyFilterType.SpanAttribute,
                operator: PropertyOperator.IContains,
                value: 'pod',
            }
            const group = toggleFacetFilter(groupWith([other]), POD_SOURCE, 'pod-a')
            const inner = (group.values[0] as UniversalFiltersGroup).values
            expect(inner).toEqual([other, expect.objectContaining({ type: PropertyFilterType.SpanResourceAttribute })])
            expect(facetFilterValues(group, POD_SOURCE)).toEqual(['pod-a'])
        })

        it('reads a scalar filter value written outside the rail as a single selection', () => {
            const group = groupWith([
                {
                    key: 'status_code',
                    type: PropertyFilterType.Span,
                    operator: PropertyOperator.Exact,
                    value: 'Error',
                },
            ])
            expect(facetFilterValues(group, STATUS_SOURCE)).toEqual(['Error'])
        })
    })
})
