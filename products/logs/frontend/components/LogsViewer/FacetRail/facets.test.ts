import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { FacetOption } from './Facet'
import {
    FACETS as CONFIGURED_FACETS,
    FacetConfig,
    FacetScope,
    cycleResourceAttributeFilter,
    facetScopeSignature,
    filterFacetsByName,
    logFilterExclusions,
    mergeSelectedIntoOptions,
    resolveFacets,
    resourceAttributeSelection,
    setLogFilterExclusions,
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
            // A value hand-edited into both polarities reaches here twice (included ++ excluded).
            [
                'a value repeated across polarities is not duplicated',
                ['dup', 'dup'],
                undefined,
                ['dup', 'api', 'worker'],
            ],
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

        describe('column facet exclusions (log filters)', () => {
            const LEVEL_KEY = 'severity_level'
            const logFilter = (
                operator: PropertyOperator,
                value: unknown,
                key: string = LEVEL_KEY
            ): Record<string, unknown> => ({ key, type: PropertyFilterType.Log, operator, value })

            it.each<[string, Record<string, unknown>[], string[]]>([
                [
                    'is_not log filter reads as exclusions',
                    [logFilter(PropertyOperator.IsNot, ['info', 'debug'])],
                    ['info', 'debug'],
                ],
                [
                    'scalar is_not chip reads as a single exclusion',
                    [logFilter(PropertyOperator.IsNot, 'info')],
                    ['info'],
                ],
                [
                    'an exact log chip on the same key is not rail state',
                    [logFilter(PropertyOperator.Exact, ['error'])],
                    [],
                ],
                [
                    'a resource-attribute filter under the same key is not a log exclusion',
                    [railFilter(PropertyOperator.IsNot, ['info'], LEVEL_KEY)],
                    [],
                ],
            ])('%s', (_, filters, excluded) => {
                expect(logFilterExclusions(groupOf(filters), LEVEL_KEY)).toEqual(excluded)
            })

            it('writes, replaces, and drops the is_not filter as the exclusion set changes', () => {
                const withOne = setLogFilterExclusions(groupOf([]), LEVEL_KEY, ['info'])
                expect(logFilterExclusions(withOne, LEVEL_KEY)).toEqual(['info'])

                const withTwo = setLogFilterExclusions(withOne, LEVEL_KEY, ['info', 'debug'])
                expect((withTwo.values[0] as UniversalFiltersGroup).values).toEqual([
                    logFilter(PropertyOperator.IsNot, ['info', 'debug']),
                ])

                const cleared = setLogFilterExclusions(withTwo, LEVEL_KEY, [])
                expect((cleared.values[0] as UniversalFiltersGroup).values).toEqual([])
            })

            it('preserves resource rail filters and same-key exact chips when writing', () => {
                const resource = railFilter(PropertyOperator.Exact, ['argocd'])
                const exactChip = logFilter(PropertyOperator.Exact, ['fatal'])
                const group = setLogFilterExclusions(groupOf([resource, exactChip]), LEVEL_KEY, ['info'])

                expect((group.values[0] as UniversalFiltersGroup).values).toEqual([
                    resource,
                    exactChip,
                    logFilter(PropertyOperator.IsNot, ['info']),
                ])
            })
        })
    })

    describe('facetScopeSignature', () => {
        const configured = (key: string): FacetConfig => CONFIGURED_FACETS.find((f) => f.key === key)!
        const LEVEL = configured('level')
        const SERVICE = configured('service')
        const NAMESPACE = configured('namespace')

        const group = (...filters: Record<string, unknown>[]): UniversalFiltersGroup => ({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: filters as UniversalFiltersGroup['values'] }],
        })
        const filter = (
            type: PropertyFilterType,
            key: string,
            operator: PropertyOperator,
            value: unknown
        ): Record<string, unknown> => ({ type, key, operator, value })

        const BASE: FacetScope = {
            currentTeamId: 1,
            utcDateRange: { date_from: '-1h', date_to: null, explicitDate: false },
            searchTerm: undefined,
            severityLevels: [],
            serviceNames: [],
            queryFilterGroup: group(),
            personId: undefined,
        }
        const signature = (facet: FacetConfig, scope: Partial<FacetScope> = {}): string =>
            facetScopeSignature(facet, { ...BASE, ...scope })

        // A facet that reacts to its own selection refetches a list the backend guarantees is
        // unchanged; one that ignores a filter it should see serves stale counts. Both are silent.
        it.each<[string, FacetConfig, Partial<FacetScope>, boolean]>([
            ['level ignores its own included levels', LEVEL, { severityLevels: ['error'] }, false],
            [
                'level ignores its own excluded levels',
                LEVEL,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.Log, 'severity_level', PropertyOperator.IsNot, ['info'])
                    ),
                },
                false,
            ],
            [
                'level ignores a severity_level chip at any operator, matching the backend strip',
                LEVEL,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.Log, 'severity_level', PropertyOperator.IContains, 'err')
                    ),
                },
                false,
            ],
            [
                'level sees a log_attribute filter under the same key, which the backend keeps',
                LEVEL,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.LogAttribute, 'severity_level', PropertyOperator.Exact, ['error'])
                    ),
                },
                true,
            ],
            ['level sees the service selection', LEVEL, { serviceNames: ['api'] }, true],
            [
                'level sees a service exclusion',
                LEVEL,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.Log, 'service_name', PropertyOperator.IsNot, ['api'])
                    ),
                },
                true,
            ],
            ['level sees the body search', LEVEL, { searchTerm: 'timeout' }, true],
            ['level sees the date range', LEVEL, { utcDateRange: { date_from: '-7d', date_to: null } }, true],
            ['level sees the person scope', LEVEL, { personId: 'abc' }, true],
            ['service ignores its own included services', SERVICE, { serviceNames: ['api'] }, false],
            [
                'service ignores its own excluded services',
                SERVICE,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.Log, 'service_name', PropertyOperator.IsNot, ['api'])
                    ),
                },
                false,
            ],
            ['service sees the level selection', SERVICE, { severityLevels: ['error'] }, true],
            [
                'namespace ignores its own included values',
                NAMESPACE,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.LogResourceAttribute, 'k8s.namespace.name', PropertyOperator.Exact, [
                            'argocd',
                        ])
                    ),
                },
                false,
            ],
            [
                'namespace ignores its own excluded values',
                NAMESPACE,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.LogResourceAttribute, 'k8s.namespace.name', PropertyOperator.IsNot, [
                            'argocd',
                        ])
                    ),
                },
                false,
            ],
            [
                'namespace sees another resource attribute',
                NAMESPACE,
                {
                    queryFilterGroup: group(
                        filter(PropertyFilterType.LogResourceAttribute, 'host.name', PropertyOperator.Exact, ['node-1'])
                    ),
                },
                true,
            ],
            [
                'namespace sees a nested filter group',
                NAMESPACE,
                {
                    queryFilterGroup: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: FilterLogicalOperator.Or,
                                        values: [
                                            filter(PropertyFilterType.LogAttribute, 'user_id', PropertyOperator.Exact, [
                                                '7',
                                            ]),
                                        ],
                                    },
                                ] as UniversalFiltersGroup['values'],
                            },
                        ],
                    },
                },
                true,
            ],
        ])('%s', (_, facet, scope, expectedToChange) => {
            expect(signature(facet, scope) !== signature(facet)).toBe(expectedToChange)
        })

        it('is identical for structurally equal filter groups', () => {
            // The signature is what the rail subscribes on: if it carried object identity rather than
            // content, every unrelated filter edit would refetch every facet again.
            const chip = (): Record<string, unknown> =>
                filter(PropertyFilterType.LogResourceAttribute, 'host.name', PropertyOperator.Exact, ['node-1'])
            expect(signature(NAMESPACE, { queryFilterGroup: group(chip()) })).toEqual(
                signature(NAMESPACE, { queryFilterGroup: group(chip()) })
            )
        })
    })

    describe('resolveFacets', () => {
        const environmentKey = (presentResourceKeys: string[]): string | undefined => {
            const facet = resolveFacets(CONFIGURED_FACETS, presentResourceKeys).find((f) => f.key === 'environment')
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
            expect(resolveFacets(CONFIGURED_FACETS, []).map((f) => f.key)).toEqual(['level', 'service'])
        })
    })
})
