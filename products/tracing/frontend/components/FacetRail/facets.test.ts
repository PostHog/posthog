import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    FacetSource,
    FilterGroupFacetSource,
    facetFilterValues,
    facetSelectedValues,
    mergeSelectedIntoOptions,
    toggleFacetFilter,
} from './facets'

const SERVICE_SOURCE: FacetSource = { type: 'column', column: 'service_name' }

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

        it('drops empty strings written by external state so they cannot become stuck filters', () => {
            const group = groupWith([
                {
                    key: 'status_code',
                    type: PropertyFilterType.Span,
                    operator: PropertyOperator.Exact,
                    value: ['Error', ''],
                },
            ])
            expect(facetFilterValues(group, STATUS_SOURCE)).toEqual(['Error'])
        })
    })

    describe('facetSelectedValues', () => {
        it('drops empty service names from external state so they cannot inject a blank row', () => {
            // The service facet reads the dedicated serviceNames field, not the filterGroup — a URL or
            // saved view carrying serviceNames: [''] must not surface a blank selected service row.
            expect(facetSelectedValues(undefined, ['api', ''], SERVICE_SOURCE)).toEqual(['api'])
        })
    })

    describe('mergeSelectedIntoOptions', () => {
        it('prepends a selected value absent from the fetched list with a zero count', () => {
            const fetched = [{ value: 'api', label: 'api', count: 5 }]
            expect(mergeSelectedIntoOptions(fetched, ['worker'])).toEqual([
                { value: 'worker', label: 'worker', count: 0 },
                { value: 'api', label: 'api', count: 5 },
            ])
        })

        it('collapses duplicate selected values into one row so keys never collide', () => {
            // A URL or saved view can carry the same value twice; two rows sharing a value would
            // collide on their React key and toggle target.
            expect(mergeSelectedIntoOptions([], ['worker', 'worker'])).toEqual([
                { value: 'worker', label: 'worker', count: 0 },
            ])
        })

        it('does not re-add a selected value already present in the fetched list', () => {
            const fetched = [{ value: 'api', label: 'api', count: 5 }]
            expect(mergeSelectedIntoOptions(fetched, ['api'])).toEqual(fetched)
        })
    })

    describe('mergeSelectedIntoOptions', () => {
        const fetched = [{ value: 'api', label: 'api', count: 10 }]

        // Injected selected-but-absent rows must honor an active type-ahead search — otherwise a
        // selected value the server just filtered out reappears pinned at 0, contradicting the list.
        it.each<[string, string | undefined, string[]]>([
            ['no search injects every missing selected value', undefined, ['worker-1']],
            ['a matching search keeps the injected value (case-insensitive)', 'WORK', ['worker-1']],
            ['a non-matching search drops the injected value', 'kafka', []],
        ])('%s', (_, search, expectedInjected) => {
            const options = mergeSelectedIntoOptions(fetched, ['api', 'worker-1'], search)
            expect(options.filter((o) => o.count === 0).map((o) => o.value)).toEqual(expectedInjected)
            expect(options).toEqual(expect.arrayContaining(fetched))
        })
    })
})
