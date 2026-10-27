import { expectLogic } from 'kea-test-utils'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    BaseMathType,
    ChartDisplayType,
    CompareLabelType,
    InsightLogicProps,
    InsightModel,
    PropertyMathType,
} from '~/types'

import { trendsDataLogic } from 'products/product_analytics/frontend/insights/trends/trendsDataLogic'
import { IndexedTrendResult } from 'products/product_analytics/frontend/insights/trends/types'

import { AggregationType, compareResultKey, insightsTableDataLogic } from './insightsTableDataLogic'

describe('insightsTableDataLogic', () => {
    let logic: ReturnType<typeof insightsTableDataLogic.build>

    describe('with dashboardItemId', () => {
        const props: InsightLogicProps = { dashboardItemId: '123' as any }

        beforeEach(() => {
            useMocks({
                get: {
                    // insightLogic mounts alongside and fetches its insight by short_id; without
                    // a match it errors with "Insight ... not found"
                    '/api/environments/:team_id/insights/': ({ request }: { request: Request }) => [
                        200,
                        {
                            results: [
                                { id: 1, short_id: new URL(request.url).searchParams.get('short_id'), query: null },
                            ],
                        },
                    ],
                },
            })
            initKeaTests()
            logic = insightsTableDataLogic(props)
            logic.mount()
        })

        describe('allowAggregation', () => {
            it('allows for trends table insight', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsTable,
                    },
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: true,
                })
            })

            it('allows with only total volume entities', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        { kind: NodeKind.EventsNode, event: '$pageview' },
                        { kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount },
                        { kind: NodeKind.EventsNode, event: '$pageview', math: PropertyMathType.Sum },
                    ],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: true,
                })
            })

            it('disallows with other math type entities', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    allowAggregation: false,
                })
            })
        })

        it.each([
            ['a breakdown of total counts', {}, true, true],
            ['no breakdown', { breakdownFilter: undefined }, false, false],
            [
                'a cohort breakdown',
                { breakdownFilter: { breakdown: [1, 'all'], breakdown_type: 'cohort' } },
                false,
                false,
            ],
            [
                'the "Other" bucket hidden',
                {
                    breakdownFilter: {
                        breakdown: '$browser',
                        breakdown_type: 'event',
                        breakdown_hide_other_aggregation: true,
                    },
                },
                false,
                false,
            ],
            [
                'unique users',
                { series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }] },
                false,
                false,
            ],
            [
                'an average of a property',
                {
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$pageview',
                            math: PropertyMathType.Average,
                            math_property: '$screen_width',
                        },
                    ],
                },
                false,
                false,
            ],
            [
                'a sum of session duration',
                {
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$pageview',
                            math: PropertyMathType.Sum,
                            math_property: '$session_duration',
                        },
                    ],
                },
                false,
                false,
            ],
            [
                'a sum of a session property',
                {
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$pageview',
                            math: PropertyMathType.Sum,
                            math_property: '$pageview_count',
                            math_property_type: 'session_properties',
                        },
                    ],
                },
                false,
                false,
            ],
            ['a formula', { trendsFilter: { formulaNodes: [{ formula: 'A * 2' }] } }, false, false],
        ] as [string, Partial<TrendsQuery>, boolean, boolean][])(
            'percent of total columns with %s',
            async (_name, overrides, expectedTotal, expectedDay) => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                    ...overrides,
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    showPercentOfTotal: expectedTotal,
                    showPercentOfDayTotal: expectedDay,
                })
            }
        )

        describe('aggregation', () => {
            it('by default averages for insights with unique math entity', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Average,
                })
            })

            it('by default totals for insights without unique math entity', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
                }

                insightVizDataLogic(props).actions.updateQuerySource(query)

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Total,
                })
            })

            it('sets aggregation type', async () => {
                const query: TrendsQuery = {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
                    trendsFilter: {},
                }

                const vizLogic = insightVizDataLogic(props)
                vizLogic.mount()

                vizLogic.actions.updateQuerySource(query)

                await expectLogic(vizLogic, () => {
                    logic.actions.setDetailedResultsAggregationType(AggregationType.Median)
                }).toFinishAllListeners()

                await expectLogic(logic).toMatchValues({
                    aggregation: AggregationType.Median,
                })
            })
        })
    })

    describe('compareResultKey', () => {
        const makeResult = (overrides: Partial<IndexedTrendResult>): IndexedTrendResult =>
            ({
                order: 0,
                label: '$pageview',
                breakdown_value: '',
                ...overrides,
            }) as IndexedTrendResult

        it.each([
            ['distinguishes by series order', makeResult({ order: 0 }), makeResult({ order: 1 }), false],
            [
                'distinguishes by breakdown value',
                makeResult({ breakdown_value: 'Chrome' }),
                makeResult({ breakdown_value: 'Firefox' }),
                false,
            ],
            [
                'distinguishes by label when order and breakdown match',
                makeResult({ label: '$pageview' }),
                makeResult({ label: '$autocapture' }),
                false,
            ],
            [
                'matches when all fields are the same',
                makeResult({ order: 0, label: '$pageview', breakdown_value: 'Chrome' }),
                makeResult({ order: 0, label: '$pageview', breakdown_value: 'Chrome' }),
                true,
            ],
            [
                'does not collide when underscore appears in label vs breakdown',
                makeResult({ label: 'a_b', breakdown_value: 'c' }),
                makeResult({ label: 'a', breakdown_value: 'b_c' }),
                false,
            ],
        ])('%s', (_name, a, b, shouldMatch) => {
            if (shouldMatch) {
                expect(compareResultKey(a)).toEqual(compareResultKey(b))
            } else {
                expect(compareResultKey(a)).not.toEqual(compareResultKey(b))
            }
        })

        it('produces valid JSON array string', () => {
            const result = compareResultKey(makeResult({ order: 2, label: 'test', breakdown_value: 'val' }))
            expect(JSON.parse(result)).toEqual([2, 'test', 'val'])
        })

        it('handles nullish fields gracefully', () => {
            const result = compareResultKey(
                makeResult({ order: undefined, label: undefined, breakdown_value: undefined } as any)
            )
            expect(JSON.parse(result)).toEqual([0, '', ''])
        })
    })

    describe('compare selectors', () => {
        const props: InsightLogicProps = { dashboardItemId: undefined }
        let builtDataNodeLogic: ReturnType<typeof dataNodeLogic.build>

        const makeCompareResult = (overrides: Partial<IndexedTrendResult>): Partial<IndexedTrendResult> => ({
            action: {
                id: '$pageview',
                type: 'events',
                order: 0,
                name: '$pageview',
                custom_name: null,
                math: null,
                math_property: null,
                math_group_type_index: null,
                properties: {},
            } as any,
            order: 0,
            label: '$pageview',
            count: 100,
            data: [10, 20, 30],
            labels: ['day1', 'day2', 'day3'],
            days: ['2023-01-01', '2023-01-02', '2023-01-03'],
            breakdown_value: '',
            persons_urls: [],
            ...overrides,
        })

        beforeEach(async () => {
            initKeaTests(false)

            builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
            builtDataNodeLogic.mount()
            await expectLogic(dataNodeLogic).toFinishAllListeners()

            insightDataLogic(props).mount()
            insightVizDataLogic(props).mount()
            trendsDataLogic(props).mount()

            logic = insightsTableDataLogic(props)
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
        })

        it('returns all results and empty map when compare is off', async () => {
            const insight: Partial<InsightModel> = {
                result: [makeCompareResult({})],
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                previousResultMap: new Map(),
            })

            expect(logic.values.displayResults).toHaveLength(1)
            expect(logic.values.getPreviousResult(logic.values.indexedResults[0])).toBeUndefined()
        })

        it('filters displayResults to current-only when compare is on', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true }),
                    makeCompareResult({ compare_label: CompareLabelType.Previous, compare: true }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toMatchValues({
                compareFilter: { compare: true },
            })

            expect(logic.values.indexedResults).toHaveLength(2)
            expect(logic.values.displayResults).toHaveLength(1)
            expect(logic.values.displayResults[0].compare_label).toBe('current')
        })

        it('builds previousResultMap keyed by compareResultKey', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$autocapture' },
                ],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Previous,
                        compare: true,
                        count: 80,
                        data: [8, 16, 24],
                    }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Current,
                        compare: true,
                        action: { order: 1, id: '$autocapture', name: '$autocapture' } as any,
                        order: 1,
                        label: '$autocapture',
                    }),
                    makeCompareResult({
                        compare_label: CompareLabelType.Previous,
                        compare: true,
                        action: { order: 1, id: '$autocapture', name: '$autocapture' } as any,
                        order: 1,
                        label: '$autocapture',
                        count: 60,
                        data: [6, 12, 18],
                    }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            expect(logic.values.previousResultMap.size).toBe(2)
            expect(logic.values.displayResults).toHaveLength(2)
            expect(logic.values.displayResults.every((r: IndexedTrendResult) => r.compare_label === 'current')).toBe(
                true
            )
        })

        it('getPreviousResult matches current items to their previous counterparts', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            }
            const insight: Partial<InsightModel> = {
                result: [
                    makeCompareResult({ compare_label: CompareLabelType.Current, compare: true, count: 100 }),
                    makeCompareResult({ compare_label: CompareLabelType.Previous, compare: true, count: 80 }),
                ],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const currentItem = logic.values.displayResults[0]
            const previousItem = logic.values.getPreviousResult(currentItem)
            expect(previousItem).not.toBeUndefined()
            expect(previousItem!.compare_label).toBe('previous')
            expect(previousItem!.count).toBe(80)
        })

        it('getPercentOfDayTotal handles results without daily data', async () => {
            const insight: Partial<InsightModel> = {
                result: [makeCompareResult({ data: null as any })],
            }

            await expectLogic(logic, () => {
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            expect(logic.values.getPercentOfDayTotal(logic.values.indexedResults[0], 0)).toBeNull()
        })

        it('unique users divide by the distinct daily totals from the backend', async () => {
            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.UniqueUsers }],
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            }
            const insight = {
                result: [
                    makeCompareResult({ breakdown_value: 'Chrome', data: [1, 2] }),
                    makeCompareResult({ breakdown_value: 'Firefox', data: [0, 1] }),
                ],
                breakdownTotals: [makeCompareResult({ data: [1, 2] })],
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const { indexedResults, getPercentOfDayTotal } = logic.values
            expect(logic.values.showPercentOfDayTotal).toBe(true)
            expect(indexedResults.map((r) => [getPercentOfDayTotal(r, 0), getPercentOfDayTotal(r, 1)])).toEqual([
                [1, 1],
                [0, 0.5],
            ])
        })

        it('percent of total divides by the total of the same series and period', async () => {
            const row = (
                order: number,
                compare_label: CompareLabelType,
                breakdown_value: string,
                data: number[]
            ): Partial<IndexedTrendResult> =>
                makeCompareResult({
                    action: { order, id: '$pageview', name: '$pageview' } as any,
                    order,
                    compare: true,
                    compare_label,
                    breakdown_value,
                    data,
                    count: data.reduce((a, b) => a + b, 0),
                })
            const insight: Partial<InsightModel> = {
                result: [
                    row(0, CompareLabelType.Current, 'Chrome', [10, 20]),
                    row(0, CompareLabelType.Current, 'Firefox', [10, 0]),
                    row(0, CompareLabelType.Previous, 'Chrome', [5, 0]),
                    row(0, CompareLabelType.Previous, 'Firefox', [5, 10]),
                    row(1, CompareLabelType.Current, 'Chrome', [50, 0]),
                ],
            }

            const query: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                ],
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
                compareFilter: { compare: true },
            }

            await expectLogic(logic, () => {
                insightVizDataLogic.findMounted(props)?.actions.updateQuerySource(query)
                builtDataNodeLogic.actions.loadDataSuccess(insight)
            }).toFinishAllListeners()

            const { indexedResults, getPercentOfTotal, getPercentOfDayTotal } = logic.values
            expect(indexedResults.map(getPercentOfTotal)).toEqual([0.75, 0.25, 0.25, 0.75, 1])
            expect(indexedResults.map((r) => [getPercentOfDayTotal(r, 0), getPercentOfDayTotal(r, 1)])).toEqual([
                [0.5, 1],
                [0.5, 0],
                [0.5, 0],
                [0.5, 1],
                [1, null],
            ])
        })
    })
})
