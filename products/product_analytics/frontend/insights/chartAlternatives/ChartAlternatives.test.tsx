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
import type { InsightVizNode, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { ChartAlternatives } from './ChartAlternatives'
import { chartAlternativesLogic } from './chartAlternativesLogic'

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

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/insights/trend': [],
                '/api/environments/:team_id/insights/': { results: [{}] },
            },
            post: {
                '/api/projects/:team_id/query/:kind/': () => new Promise(() => {}),
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
        return chartAlternativesLogic.findMounted({ editMode: true, embedded: false, ...insightProps })!
    }

    function currentTrendsQuery(): TrendsQuery {
        return (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
    }

    it('applies the display rewrite when a chart is selected and closes the gallery', () => {
        setQuery(
            makeTrendsQuery({
                breakdownFilter: { breakdown: 'browser', breakdown_type: 'event' },
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A / B' },
            })
        )
        const logic = alternativesLogic()
        logic.actions.openGallery()
        expect(logic.values.galleryOpen).toBe(true)

        logic.actions.selectChart(ChartDisplayType.BoxPlot, 'gallery')

        expect(currentTrendsQuery().trendsFilter).toMatchObject({
            display: ChartDisplayType.BoxPlot,
            formula: undefined,
            formulaNodes: [],
        })
        expect(currentTrendsQuery().breakdownFilter).toBeUndefined()
        expect(logic.values.galleryOpen).toBe(false)
    })

    it('ignores selecting the current chart or a disabled one', () => {
        const base = makeTrendsQuery()
        setQuery({
            ...base,
            series: [...base.series, { kind: NodeKind.EventsNode, event: '$pageleave', math: BaseMathType.TotalCount }],
            breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'event' },
            trendsFilter: { display: ChartDisplayType.WorldMap },
        })
        const logic = alternativesLogic()
        const originalQuery = builtInsightDataLogic.values.query
        expect(
            logic.values.options.flatMap((g) => g.options).find((o) => o.display === ChartDisplayType.BoldNumber)
                ?.disabledReason
        ).toBeTruthy()

        logic.actions.selectChart(ChartDisplayType.WorldMap, 'recommended')
        logic.actions.selectChart(ChartDisplayType.BoldNumber, 'gallery')

        expect(builtInsightDataLogic.values.query).toEqual(originalQuery)
    })

    it('renders the chart switch control only while the flag is on', async () => {
        setQuery(makeTrendsQuery())
        alternativesLogic()
        await waitFor(() => expect(document.querySelector('[data-attr="chart-alternatives-all"]')).toBeInTheDocument())

        featureFlagLogic.actions.setFeatureFlags([], {})
        await waitFor(() =>
            expect(document.querySelector('[data-attr="chart-alternatives-all"]')).not.toBeInTheDocument()
        )
    })
})
