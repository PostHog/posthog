import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    FacetSelection,
    FacetSource,
    FilterGroupFacetSource,
    cycleFacetFilter,
    facetFilterSelection,
    facetSelection,
    mergeSelectedIntoOptions,
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
    describe('cycleFacetFilter / facetFilterSelection', () => {
        const read = (group: UniversalFiltersGroup | undefined, source: FilterGroupFacetSource): FacetSelection =>
            facetFilterSelection(group, source)

        it.each<[string, FilterGroupFacetSource, PropertyFilterType]>([
            ['column facet writes a span filter', STATUS_SOURCE, PropertyFilterType.Span],
            [
                'resource-attribute facet writes a span_resource_attribute filter',
                POD_SOURCE,
                PropertyFilterType.SpanResourceAttribute,
            ],
        ])('%s', (_, source, expectedType) => {
            const group = cycleFacetFilter(undefined, source, 'a')
            const inner = (group.values[0] as UniversalFiltersGroup).values
            expect(inner).toEqual([
                expect.objectContaining({ type: expectedType, operator: PropertyOperator.Exact, value: ['a'] }),
            ])
            expect(read(group, source)).toEqual({ included: ['a'], excluded: [] })
        })

        it('cycles a value unchecked → included → excluded → unchecked, dropping emptied filters', () => {
            const afterFirst = cycleFacetFilter(undefined, POD_SOURCE, 'pod-a')
            expect(read(afterFirst, POD_SOURCE)).toEqual({ included: ['pod-a'], excluded: [] })

            const afterSecond = cycleFacetFilter(afterFirst, POD_SOURCE, 'pod-a')
            expect(read(afterSecond, POD_SOURCE)).toEqual({ included: [], excluded: ['pod-a'] })

            const afterThird = cycleFacetFilter(afterSecond, POD_SOURCE, 'pod-a')
            expect((afterThird.values[0] as UniversalFiltersGroup).values).toEqual([])
        })

        it('writes includes as an exact filter and excludes as an is_not filter, both array-valued', () => {
            let group = cycleFacetFilter(undefined, POD_SOURCE, 'pod-a')
            group = cycleFacetFilter(group, POD_SOURCE, 'pod-b')
            group = cycleFacetFilter(group, POD_SOURCE, 'pod-a') // pod-a → excluded

            expect((group.values[0] as UniversalFiltersGroup).values).toEqual([
                expect.objectContaining({ operator: PropertyOperator.Exact, value: ['pod-b'] }),
                expect.objectContaining({ operator: PropertyOperator.IsNot, value: ['pod-a'] }),
            ])
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
            const group = cycleFacetFilter(groupWith([other]), POD_SOURCE, 'pod-a')
            const inner = (group.values[0] as UniversalFiltersGroup).values
            expect(inner).toEqual([other, expect.objectContaining({ type: PropertyFilterType.SpanResourceAttribute })])
            expect(read(group, POD_SOURCE)).toEqual({ included: ['pod-a'], excluded: [] })
        })

        it.each<[string, PropertyOperator, unknown, FacetSelection]>([
            [
                'a scalar exact chip written outside the rail reads as a single inclusion',
                PropertyOperator.Exact,
                'Error',
                { included: ['Error'], excluded: [] },
            ],
            [
                'a scalar is_not chip written outside the rail reads as a single exclusion',
                PropertyOperator.IsNot,
                'Error',
                { included: [], excluded: ['Error'] },
            ],
            [
                'empty strings from external state are dropped so they cannot become stuck filters',
                PropertyOperator.Exact,
                ['Error', ''],
                { included: ['Error'], excluded: [] },
            ],
            [
                'a non-rail operator chip is not rail state',
                PropertyOperator.IContains,
                'Error',
                { included: [], excluded: [] },
            ],
        ])('%s', (_, operator, value, expected) => {
            const group = groupWith([{ key: 'status_code', type: PropertyFilterType.Span, operator, value }])
            expect(read(group, STATUS_SOURCE)).toEqual(expected)
        })
    })

    describe('facetSelection', () => {
        it('drops empty service names from external state so they cannot inject a blank row', () => {
            // The service facet reads the dedicated serviceNames field, not the filterGroup — a URL or
            // saved view carrying serviceNames: [''] must not surface a blank selected service row.
            expect(facetSelection(undefined, ['api', ''], SERVICE_SOURCE)).toEqual({
                included: ['api'],
                excluded: [],
            })
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
