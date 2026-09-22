import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import {
    FACETS,
    FacetConfig,
    FacetScope,
    FacetSelection,
    FacetSource,
    FilterGroupFacetSource,
    buildCustomFacet,
    customFacetIdentity,
    cycleFacetFilter,
    facetFilterSelection,
    facetScopeSignature,
    facetSelection,
    facetValueGroup,
    mergeSelectedIntoOptions,
    resolveFacets,
} from './facets'

const SERVICE_SOURCE: FacetSource = { type: 'column', column: 'service_name' }

const STATUS_SOURCE: FilterGroupFacetSource = { type: 'column', column: 'status_code' }
const POD_SOURCE: FilterGroupFacetSource = { type: 'resourceAttribute', key: 'k8s.pod.name' }
const HTTP_STATUS_ATTRIBUTE_SOURCE: FilterGroupFacetSource = { type: 'attribute', key: 'http.status_code' }

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
            [
                'plain-attribute facet writes a span_attribute filter',
                HTTP_STATUS_ATTRIBUTE_SOURCE,
                PropertyFilterType.SpanAttribute,
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

    describe('facetValueGroup', () => {
        it.each<[string, FacetSource, string, string[]]>([
            ['status_code OK folds in Unset', STATUS_SOURCE, '1', ['0', '1']],
            ['status_code Error is its own singleton', STATUS_SOURCE, '2', ['2']],
            ['a resource-attribute source passes its value through unchanged', POD_SOURCE, 'pod-a', ['pod-a']],
        ])('%s', (_, source, value, expected) => {
            expect(facetValueGroup(source, value)).toEqual(expected)
        })
    })

    describe('cycleFacetFilter folds status_code Unset into OK', () => {
        it('selecting OK ("1") writes both "0" and "1" into the exact filter', () => {
            const group = cycleFacetFilter(undefined, STATUS_SOURCE, '1')
            const inner = (group.values[0] as UniversalFiltersGroup).values
            expect(inner).toEqual([expect.objectContaining({ operator: PropertyOperator.Exact, value: ['0', '1'] })])
        })

        it('deselecting OK moves both "0" and "1" to the is_not filter, not just "1"', () => {
            const included = cycleFacetFilter(undefined, STATUS_SOURCE, '1')
            const excluded = cycleFacetFilter(included, STATUS_SOURCE, '1')
            expect(facetFilterSelection(excluded, STATUS_SOURCE)).toEqual({ included: [], excluded: ['0', '1'] })
        })

        it('upgrades a filter with only the pre-fold single digit "1" to the full group on toggle', () => {
            const legacy = groupWith([
                { key: 'status_code', type: PropertyFilterType.Span, operator: PropertyOperator.Exact, value: ['1'] },
            ])
            const excluded = cycleFacetFilter(legacy, STATUS_SOURCE, '1')
            expect(facetFilterSelection(excluded, STATUS_SOURCE)).toEqual({ included: [], excluded: ['0', '1'] })
        })

        it.each<[string, PropertyOperator]>([
            ['included', PropertyOperator.Exact],
            ['excluded', PropertyOperator.IsNot],
        ])('reports a pre-fold Unset-only ("0") %s filter against the OK row', (_, operator) => {
            // Before the fold, Unset was its own row, so a saved view or URL can carry "0" alone. The
            // OK row has to render it as active, or the first click reads as "select OK" while it
            // actually cycles the already-active group straight to excluded.
            const legacy = groupWith([{ key: 'status_code', type: PropertyFilterType.Span, operator, value: ['0'] }])
            const expected =
                operator === PropertyOperator.Exact
                    ? { included: ['1'], excluded: [] }
                    : { included: [], excluded: ['1'] }
            expect(facetSelection(legacy, null, STATUS_SOURCE)).toEqual(expected)
        })

        it('completes a pre-fold Unset-only group when a different row is toggled', () => {
            // Clicking Error must not leave "0" behind without "1": the rail would show OK selected
            // while the query dropped every explicitly-OK span.
            const legacy = groupWith([
                { key: 'status_code', type: PropertyFilterType.Span, operator: PropertyOperator.Exact, value: ['0'] },
            ])
            const group = cycleFacetFilter(legacy, STATUS_SOURCE, '2')
            expect(facetFilterSelection(group, STATUS_SOURCE)).toEqual({ included: ['0', '1', '2'], excluded: [] })
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

    describe('facetScopeSignature', () => {
        const configured = (key: string): FacetConfig => FACETS.find((f) => f.key === key)!
        const SERVICE = configured('service')
        const STATUS = configured('status')
        const NAMESPACE = configured('namespace')

        const filter = (type: PropertyFilterType, key: string, operator: PropertyOperator, value: unknown): object => ({
            type,
            key,
            operator,
            value,
        })

        const BASE: FacetScope = {
            currentTeamId: 1,
            utcDateRange: { date_from: '-1h', date_to: null },
            serviceNames: [],
            queryFilterGroup: groupWith([]),
        }
        const signature = (facet: FacetConfig, scope: Partial<FacetScope> = {}): string =>
            facetScopeSignature(facet, { ...BASE, ...scope })

        // A facet that reacts to its own selection refetches a list excludeBreakdownFilter guarantees
        // is unchanged; one that ignores a filter it should see serves stale counts. Both are silent.
        it.each<[string, FacetConfig, Partial<FacetScope>, boolean]>([
            ['service ignores its own selection', SERVICE, { serviceNames: ['api'] }, false],
            [
                'service ignores a span filter on its own column, at any operator',
                SERVICE,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.Span, 'service_name', PropertyOperator.IContains, 'ap'),
                    ]),
                },
                false,
            ],
            [
                'service sees the status selection',
                SERVICE,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.Span, 'status_code', PropertyOperator.Exact, ['2']),
                    ]),
                },
                true,
            ],
            ['service sees the date range', SERVICE, { utcDateRange: { date_from: '-7d', date_to: null } }, true],
            [
                'status ignores its own selection',
                STATUS,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.Span, 'status_code', PropertyOperator.Exact, ['2']),
                    ]),
                },
                false,
            ],
            ['status sees the service selection', STATUS, { serviceNames: ['api'] }, true],
            [
                'namespace ignores its own values, either polarity',
                NAMESPACE,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.SpanResourceAttribute, 'k8s.namespace.name', PropertyOperator.IsNot, [
                            'argocd',
                        ]),
                    ]),
                },
                false,
            ],
            [
                'namespace sees a span_attribute filter under the same key, which the backend keeps',
                NAMESPACE,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.SpanAttribute, 'k8s.namespace.name', PropertyOperator.Exact, [
                            'argocd',
                        ]),
                    ]),
                },
                true,
            ],
            [
                'namespace sees another resource attribute',
                NAMESPACE,
                {
                    queryFilterGroup: groupWith([
                        filter(PropertyFilterType.SpanResourceAttribute, 'host.name', PropertyOperator.Exact, [
                            'node-1',
                        ]),
                    ]),
                },
                true,
            ],
        ])('%s', (_, facet, scope, expectedToChange) => {
            expect(signature(facet, scope) !== signature(facet)).toBe(expectedToChange)
        })

        it('is identical for structurally equal filter groups', () => {
            // The signature is what the rail subscribes on: if it carried object identity rather than
            // content, every unrelated filter edit would refetch every facet again.
            const chip = (): object =>
                filter(PropertyFilterType.SpanResourceAttribute, 'host.name', PropertyOperator.Exact, ['node-1'])
            expect(signature(NAMESPACE, { queryFilterGroup: groupWith([chip()]) })).toEqual(
                signature(NAMESPACE, { queryFilterGroup: groupWith([chip()]) })
            )
        })
    })

    describe('resolveFacets', () => {
        const environmentKey = (presentResourceKeys: string[]): string | undefined => {
            const facet = resolveFacets(FACETS, presentResourceKeys).find((f) => f.key === 'environment')
            return facet?.source.type === 'resourceAttribute' ? facet.source.key : undefined
        }

        // The rail queries and filters on whichever key resolution picks, so picking the wrong one (or
        // none) silently hides a facet the tenant's data can populate.
        it.each<[string, string[], string | undefined]>([
            ['the current key is used as-is', ['deployment.environment.name'], 'deployment.environment.name'],
            ['the superseded key still resolves', ['deployment.environment'], 'deployment.environment'],
            ['a datadog env tag still resolves', ['env'], 'env'],
            [
                'the current key wins over its aliases',
                ['env', 'deployment.environment', 'deployment.environment.name'],
                'deployment.environment.name',
            ],
            ['no spelling emitted drops the facet', ['k8s.pod.name'], undefined],
        ])('%s', (_, presentResourceKeys, expected) => {
            expect(environmentKey(presentResourceKeys)).toEqual(expected)
        })

        it('keeps column facets whatever the tenant emits', () => {
            expect(resolveFacets(FACETS, []).map((f) => f.key)).toEqual(['service', 'status'])
        })

        it('passes a plain-attribute facet through unchanged, regardless of presence', () => {
            // Custom facets are added by the user picking a real key, not resolved against a curated
            // alias list — resolveFacets must never drop or rewrite them the way it does resourceAttribute.
            const attributeFacet = buildCustomFacet('http.status_code', 'attribute')
            expect(resolveFacets([attributeFacet], [])).toEqual([attributeFacet])
        })
    })

    describe('buildCustomFacet / customFacetIdentity', () => {
        it.each<['attribute' | 'resourceAttribute']>([['attribute'], ['resourceAttribute']])(
            'round-trips the key and sourceType through a %s facet',
            (sourceType) => {
                const facet = buildCustomFacet('http.status_code', sourceType)
                expect(customFacetIdentity(facet)).toEqual({ key: 'http.status_code', sourceType })
            }
        )

        it('returns null for a curated facet', () => {
            expect(customFacetIdentity(FACETS[0])).toBeNull()
        })
    })
})
