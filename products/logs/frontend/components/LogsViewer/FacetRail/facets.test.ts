import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { FacetOption } from './Facet'
import {
    FacetConfig,
    cycleResourceAttributeFilter,
    filterFacetsByName,
    mergeSelectedIntoOptions,
    resourceAttributeSelection,
} from './facets'

const facet = (key: string, title: string, group: string): FacetConfig => ({
    key,
    title,
    group,
    kind: 'dynamic',
    source: { type: 'resourceAttribute', key },
})

const FACETS: FacetConfig[] = [
    facet('level', 'Level', 'Standard'),
    facet('service', 'Service', 'Standard'),
    facet('namespace', 'Namespace', 'Kubernetes'),
    facet('pod', 'Pod', 'Kubernetes'),
    facet('host', 'Host', 'Infrastructure'),
]

describe('facets', () => {
    describe('filterFacetsByName', () => {
        it.each([
            ['blank query returns all', '', ['level', 'service', 'namespace', 'pod', 'host']],
            ['whitespace-only returns all', '   ', ['level', 'service', 'namespace', 'pod', 'host']],
            ['matches a field title', 'namespace', ['namespace']],
            ['title match is case-insensitive', 'NAMESPACE', ['namespace']],
            ['partial title match', 'serv', ['service']],
            ['matches a whole group by name', 'kubernetes', ['namespace', 'pod']],
            ['group match is case-insensitive', 'INFRA', ['host']],
            ['no match returns empty', 'zzz', []],
        ])('%s', (_, query, expectedKeys) => {
            expect(filterFacetsByName(FACETS, query).map((f) => f.key)).toEqual(expectedKeys)
        })
    })

    describe('mergeSelectedIntoOptions', () => {
        const fetched: FacetOption[] = [
            { value: 'api', label: 'api', count: 10 },
            { value: 'worker', label: 'worker', count: 5 },
        ]

        it.each<[string, string[], string | undefined, string[]]>([
            ['no selected values leaves fetched unchanged', [], undefined, ['api', 'worker']],
            ['selected value already fetched is not duplicated', ['api'], undefined, ['api', 'worker']],
            ['missing selected value is prepended', ['batch-exports'], undefined, ['batch-exports', 'api', 'worker']],
            ['multiple missing values keep selection order', ['b', 'a'], undefined, ['b', 'a', 'api', 'worker']],
            ['missing selected value not matching the search is omitted', ['batch-exports'], 'api', ['api', 'worker']],
            [
                'search match is a case-insensitive substring',
                ['Batch-Exports'],
                'batch',
                ['Batch-Exports', 'api', 'worker'],
            ],
        ])('%s', (_, selected, search, expectedValues) => {
            expect(mergeSelectedIntoOptions(fetched, selected, search).map((o) => o.value)).toEqual(expectedValues)
        })

        it('injects missing selected values with a zero count', () => {
            expect(mergeSelectedIntoOptions(fetched, ['batch-exports'], undefined)[0]).toEqual({
                value: 'batch-exports',
                label: 'batch-exports',
                count: 0,
            })
        })
    })

    describe('tri-state resource attribute selection', () => {
        const KEY = 'k8s.namespace.name'

        const groupOf = (filters: Record<string, unknown>[]): UniversalFiltersGroup => ({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: filters as UniversalFiltersGroup['values'] }],
        })
        const railFilter = (
            operator: PropertyOperator,
            value: unknown,
            key: string = KEY
        ): Record<string, unknown> => ({
            key,
            type: PropertyFilterType.LogResourceAttribute,
            operator,
            value,
        })
        const read = (group: UniversalFiltersGroup | undefined): { included: string[]; excluded: string[] } =>
            resourceAttributeSelection(group, KEY)

        describe('resourceAttributeSelection', () => {
            it.each<[string, Record<string, unknown>[], string[], string[]]>([
                ['empty group reads as empty selection', [], [], []],
                [
                    'exact array filter reads as included',
                    [railFilter(PropertyOperator.Exact, ['a', 'b'])],
                    ['a', 'b'],
                    [],
                ],
                ['is_not array filter reads as excluded', [railFilter(PropertyOperator.IsNot, ['c'])], [], ['c']],
                [
                    'both polarities read into their own sets',
                    [railFilter(PropertyOperator.Exact, ['a']), railFilter(PropertyOperator.IsNot, ['c'])],
                    ['a'],
                    ['c'],
                ],
                [
                    'scalar chip value reads as a single-element set',
                    [railFilter(PropertyOperator.Exact, 'a')],
                    ['a'],
                    [],
                ],
                ['scalar is_not chip reads as excluded', [railFilter(PropertyOperator.IsNot, 'c')], [], ['c']],
                ['other operators are not rail state', [railFilter(PropertyOperator.IContains, 'a')], [], []],
                ['other keys are not this facet', [railFilter(PropertyOperator.Exact, ['a'], 'host.name')], [], []],
            ])('%s', (_, filters, included, excluded) => {
                expect(read(groupOf(filters))).toEqual({ included, excluded })
            })
        })

        describe('cycleResourceAttributeFilter', () => {
            it('cycles a value unchecked → included → excluded → unchecked', () => {
                const afterFirst = cycleResourceAttributeFilter(groupOf([]), KEY, 'argocd')
                expect(read(afterFirst)).toEqual({ included: ['argocd'], excluded: [] })

                const afterSecond = cycleResourceAttributeFilter(afterFirst, KEY, 'argocd')
                expect(read(afterSecond)).toEqual({ included: [], excluded: ['argocd'] })

                const afterThird = cycleResourceAttributeFilter(afterSecond, KEY, 'argocd')
                expect(read(afterThird)).toEqual({ included: [], excluded: [] })
                // both rail filters are dropped once their side of the selection empties
                expect((afterThird.values[0] as UniversalFiltersGroup).values).toEqual([])
            })

            it('writes includes as an exact filter and excludes as an is_not filter, both array-valued', () => {
                let group = cycleResourceAttributeFilter(groupOf([]), KEY, 'a')
                group = cycleResourceAttributeFilter(group, KEY, 'b')
                group = cycleResourceAttributeFilter(group, KEY, 'a') // a → excluded

                expect((group.values[0] as UniversalFiltersGroup).values).toEqual([
                    railFilter(PropertyOperator.Exact, ['b']),
                    railFilter(PropertyOperator.IsNot, ['a']),
                ])
            })

            it('preserves other keys and same-key non-rail chips when writing', () => {
                const otherKey = railFilter(PropertyOperator.Exact, ['prod'], 'deployment.environment.name')
                const sameKeyContains = railFilter(PropertyOperator.IContains, 'kube')
                const group = cycleResourceAttributeFilter(groupOf([otherKey, sameKeyContains]), KEY, 'argocd')

                expect((group.values[0] as UniversalFiltersGroup).values).toEqual([
                    otherKey,
                    sameKeyContains,
                    railFilter(PropertyOperator.Exact, ['argocd']),
                ])
            })

            it('a value in both polarities (hand-edited chips) cycles to excluded only, without duplication', () => {
                const corrupt = groupOf([
                    railFilter(PropertyOperator.Exact, ['a']),
                    railFilter(PropertyOperator.IsNot, ['a']),
                ])
                expect(read(cycleResourceAttributeFilter(corrupt, KEY, 'a'))).toEqual({
                    included: [],
                    excluded: ['a'],
                })
            })
        })
    })
})
