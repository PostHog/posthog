import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { metricFiltersForGroup } from '../metricsViewerLogic'
import { buildMetricFacets, cycleMetricFacetFilter, metricFacetSelection } from './facets'

const group = (values: Record<string, unknown>[]): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [{ type: FilterLogicalOperator.And, values: values as any }],
})

const EMPTY = group([])

describe('metrics facets', () => {
    describe('buildMetricFacets', () => {
        it.each([
            ['service always comes first', ['env', 'region'], ['service_name', 'env', 'region']],
            [
                'both service spellings fold into the service facet',
                ['service.name', 'env', 'service_name'],
                ['service_name', 'env'],
            ],
            ['duplicate keys render once', ['env', 'env'], ['service_name', 'env']],
            ['no keys still offers service', [], ['service_name']],
        ])('%s', (_, keys, expected) => {
            expect(buildMetricFacets(keys).map((facet) => facet.attributeKey)).toEqual(expected)
        })
    })

    describe('cycleMetricFacetFilter / metricFacetSelection', () => {
        it('cycles a value through included, excluded and cleared', () => {
            const included = cycleMetricFacetFilter(EMPTY, 'env', 'prod')
            expect(metricFacetSelection(included, 'env')).toEqual({ included: ['prod'], excluded: [] })

            const excluded = cycleMetricFacetFilter(included, 'env', 'prod')
            expect(metricFacetSelection(excluded, 'env')).toEqual({ included: [], excluded: ['prod'] })

            const cleared = cycleMetricFacetFilter(excluded, 'env', 'prod')
            expect(metricFacetSelection(cleared, 'env')).toEqual({ included: [], excluded: [] })
            expect(cleared).toEqual(EMPTY)
        })

        it.each(['service.name', 'service_name'])(
            'reads and replaces a %s chip from the filter bar on the service facet',
            (chipKey) => {
                const fromFilterBar = group([
                    {
                        key: chipKey,
                        type: PropertyFilterType.MetricAttribute,
                        operator: PropertyOperator.Exact,
                        value: ['checkout'],
                    },
                ])
                expect(metricFacetSelection(fromFilterBar, 'service_name')).toEqual({
                    included: ['checkout'],
                    excluded: [],
                })

                const excluded = cycleMetricFacetFilter(fromFilterBar, 'service_name', 'checkout')
                expect((excluded.values[0] as UniversalFiltersGroup).values).toEqual([
                    {
                        key: 'service_name',
                        type: PropertyFilterType.MetricAttribute,
                        operator: PropertyOperator.IsNot,
                        value: ['checkout'],
                    },
                ])
            }
        )

        it('adds a second value to the same include filter', () => {
            const next = cycleMetricFacetFilter(cycleMetricFacetFilter(EMPTY, 'env', 'prod'), 'env', 'dev')
            expect(metricFacetSelection(next, 'env')).toEqual({ included: ['prod', 'dev'], excluded: [] })
        })

        it('keeps chips the rail does not own', () => {
            const regexChip = {
                key: 'env',
                type: PropertyFilterType.MetricAttribute,
                operator: PropertyOperator.Regex,
                value: ['pr.*'],
            }
            const otherKey = {
                key: 'region',
                type: PropertyFilterType.MetricAttribute,
                operator: PropertyOperator.Exact,
                value: ['us'],
            }
            const next = cycleMetricFacetFilter(group([regexChip, otherKey]), 'env', 'prod')
            expect((next.values[0] as UniversalFiltersGroup).values).toEqual([
                regexChip,
                otherKey,
                {
                    key: 'env',
                    type: PropertyFilterType.MetricAttribute,
                    operator: PropertyOperator.Exact,
                    value: ['prod'],
                },
            ])
            expect(metricFacetSelection(next, 'env')).toEqual({ included: ['prod'], excluded: [] })
        })

        it('writes filters the metrics query sends as matchers', () => {
            const next = cycleMetricFacetFilter(
                cycleMetricFacetFilter(cycleMetricFacetFilter(EMPTY, 'env', 'prod'), 'region', 'us'),
                'region',
                'us'
            )
            expect(metricFiltersForGroup(next)).toEqual([
                { key: 'env', op: 'eq', value: 'prod' },
                { key: 'region', op: 'neq', value: 'us' },
            ])
        })
    })
})
