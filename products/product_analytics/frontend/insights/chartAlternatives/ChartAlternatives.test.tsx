import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { ChartAlternatives } from './ChartAlternatives'
import { chartAlternativesLogic } from './chartAlternativesLogic'
import { getChartAlternatives, getChartDisplayChangeWarning, getChartDisplayOptions } from './chartDisplayOptions'

const insightProps = { dashboardItemId: 'chart-alternatives' as InsightShortId }

function makeTrendsQuery(overrides: Partial<TrendsQuery> = {}): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [
            {
                kind: NodeKind.EventsNode,
                name: '$pageview',
                event: '$pageview',
                math: BaseMathType.TotalCount,
                math_property: 'duration',
            },
        ],
        trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        ...overrides,
    }
}

describe('ChartAlternatives', () => {
    let builtInsightDataLogic: ReturnType<typeof insightDataLogic.build>
    let builtInsightVizDataLogic: ReturnType<typeof insightVizDataLogic.build>
    let resolveQueryResponse: (() => void) | null

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
            post: {
                '/api/projects/:team_id/query/:kind/': () =>
                    new Promise((resolve) => {
                        resolveQueryResponse = () => resolve({ results: [] })
                    }),
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES], {
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES]: true,
        })

        insightLogic(insightProps).mount()
        builtInsightDataLogic = insightDataLogic(insightProps)
        builtInsightVizDataLogic = insightVizDataLogic(insightProps)
        builtInsightDataLogic.mount()
        builtInsightVizDataLogic.mount()
    })

    afterEach(() => {
        cleanup()
        chartAlternativesLogic.findMounted({ editMode: true, embedded: false, ...insightProps })?.unmount()
    })

    function setQuery(query: TrendsQuery): void {
        builtInsightVizDataLogic.actions.updateQuerySource(query)
    }

    function alternativesLogic(): ReturnType<typeof chartAlternativesLogic.build> {
        render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <ChartAlternatives insightProps={insightProps} editMode embedded={false} />
                </BindLogic>
            </Provider>
        )
        const logic = chartAlternativesLogic.findMounted({ editMode: true, embedded: false, ...insightProps })
        if (!logic) {
            throw new Error('Expected chart alternatives logic to mount')
        }
        return logic
    }

    function currentTrendsQuery(): TrendsQuery {
        const query = builtInsightDataLogic.values.query
        if (!isInsightVizNode(query) || !isTrendsQuery(query.source)) {
            throw new Error('Expected a Trends insight query')
        }
        return query.source
    }

    it('preserves the complete query across a destructive chart selection and return', async () => {
        setQuery(
            makeTrendsQuery({
                breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A / B' },
            })
        )
        const logic = alternativesLogic()
        const originalQuery = builtInsightDataLogic.values.query

        logic.actions.selectChart(ChartDisplayType.BoxPlot, 'gallery')
        expect(logic.values.pendingSelection).not.toBeNull()
        logic.actions.confirmSelection()

        expect(currentTrendsQuery().trendsFilter).toMatchObject({
            display: ChartDisplayType.BoxPlot,
            formula: undefined,
            formulaNodes: [],
        })
        expect(currentTrendsQuery().breakdownFilter).toBeUndefined()

        builtInsightVizDataLogic.actions.loadData()
        await waitFor(() => expect(builtInsightVizDataLogic.values.insightDataLoading).toBe(true))
        expect(logic.values.canReturn).toBe(true)
        logic.actions.returnToOriginal()
        expect(builtInsightDataLogic.values.query).toEqual(originalQuery)
        resolveQueryResponse?.()
    })

    it('does not apply a confirmation after the query changes during loading', async () => {
        setQuery(
            makeTrendsQuery({
                breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A / B' },
            })
        )
        const logic = alternativesLogic()
        logic.actions.selectChart(ChartDisplayType.ActionsAreaGraph, 'strip')
        expect(logic.values.canReturn).toBe(true)
        logic.actions.selectChart(ChartDisplayType.BoxPlot, 'gallery')
        expect(logic.values.pendingSelection).not.toBeNull()

        builtInsightVizDataLogic.actions.loadData()
        await waitFor(() => expect(builtInsightVizDataLogic.values.insightDataLoading).toBe(true))
        builtInsightVizDataLogic.actions.updateQuerySource({ dateRange: { date_from: '-30d' } })

        logic.actions.confirmSelection()
        expect(logic.values.pendingSelection).toBeNull()
        expect(logic.values.canReturn).toBe(false)
        expect(currentTrendsQuery().trendsFilter?.display).toBe(ChartDisplayType.ActionsAreaGraph)
        resolveQueryResponse?.()
    })

    it('keeps the current map query unchanged and only renders enabled chart controls', async () => {
        setQuery(
            makeTrendsQuery({
                breakdownFilter: { breakdown: '$geoip_country_name', breakdown_type: 'person' },
                trendsFilter: { display: ChartDisplayType.WorldMap },
            })
        )
        const logic = alternativesLogic()
        const originalQuery = builtInsightDataLogic.values.query
        logic.actions.selectChart(ChartDisplayType.WorldMap, 'strip')
        expect(builtInsightDataLogic.values.query).toEqual(originalQuery)

        expect(document.querySelector('[data-attr="chart-alternative-WorldMap"]')).toHaveAttribute(
            'aria-pressed',
            'true'
        )
        builtInsightVizDataLogic.actions.loadData()
        await waitFor(() => {
            expect(document.querySelector('[data-attr="chart-alternative-BoxPlot"]')).toHaveAttribute(
                'aria-disabled',
                'true'
            )
        })
        featureFlagLogic.actions.setFeatureFlags([], {})
        await waitFor(() => expect(document.querySelector('[data-attr="chart-alternatives"]')).not.toBeInTheDocument())
        resolveQueryResponse?.()
    })

    it('uses the same eligibility metadata as the chart dropdown', () => {
        const options = getChartDisplayOptions({
            isTrends: true,
            hasSingleSeriesOutput: false,
            hasTrendsFormula: true,
            breakdown: 'browser',
            boxPlotMissingProperty: true,
            hasMetricInsight: false,
        })
        const optionsByDisplay = new Map(
            options.flatMap((group) => group.options).map((option) => [option.display, option])
        )

        expect(optionsByDisplay.get(ChartDisplayType.BoldNumber)?.disabledReason).toBe(
            'This type currently only supports insights with one series, and this insight has multiple series.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.BoxPlot)?.disabledReason).toBe(
            'Select a numeric property to use a box plot.'
        )
        expect(optionsByDisplay.get(ChartDisplayType.WorldMap)?.disabledReason).toBe(
            "This type isn't available, because it doesn't support formulas."
        )
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.BoxPlot,
                makeTrendsQuery({
                    breakdownFilter: {
                        breakdown: 'browser',
                        breakdown_type: 'event',
                        breakdowns: [{ property: 'browser', type: 'event' }],
                    },
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                        formulaNodes: [{ formula: 'A / B', custom_name: '' }],
                    },
                })
            )?.title
        ).toBe('This chart type removes the breakdown and formula')
        expect(
            getChartDisplayChangeWarning(
                ChartDisplayType.WorldMap,
                makeTrendsQuery({
                    breakdownFilter: { breakdown: '$geoip_country_name', breakdown_type: 'person' },
                })
            )?.title
        ).toBe('This chart type changes the breakdown to Country code')

        const compatibleOptions = getChartDisplayOptions({
            isTrends: true,
            hasSingleSeriesOutput: true,
            hasTrendsFormula: false,
            boxPlotMissingProperty: false,
            hasMetricInsight: true,
        })
        expect(
            getChartAlternatives(compatibleOptions, ChartDisplayType.ActionsLineGraph, {
                breakdown: '$geoip_country_code',
            }).map((option) => option.display)
        ).toEqual([
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.BoxPlot,
            ChartDisplayType.WorldMap,
            ChartDisplayType.Metric,
        ])
        expect(
            getChartAlternatives(compatibleOptions, ChartDisplayType.ActionsLineGraph).map((option) => option.display)
        ).toEqual([
            ChartDisplayType.ActionsLineGraph,
            ChartDisplayType.BoxPlot,
            ChartDisplayType.Metric,
            ChartDisplayType.ActionsTable,
        ])
    })
})
