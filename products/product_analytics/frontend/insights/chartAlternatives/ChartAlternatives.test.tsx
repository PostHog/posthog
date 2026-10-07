import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

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
import { chartPreviewsLogic } from './chartPreviewsLogic'

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
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES]: 'test',
        })

        insightLogic(insightProps).mount()
        builtInsightDataLogic = insightDataLogic(insightProps)
        builtInsightVizDataLogic = insightVizDataLogic(insightProps)
        builtInsightDataLogic.mount()
        builtInsightVizDataLogic.mount()
    })

    afterEach(() => {
        cleanup()
        chartAlternativesLogic.findMounted({ embedded: false, ...insightProps })?.unmount()
    })

    function setQuery(query: TrendsQuery): void {
        builtInsightVizDataLogic.actions.updateQuerySource(query)
    }

    function alternativesLogic(): ReturnType<typeof chartAlternativesLogic.build> {
        render(
            <Provider>
                <BindLogic logic={insightLogic} props={insightProps}>
                    <ChartAlternatives insightProps={insightProps} embedded={false} />
                </BindLogic>
            </Provider>
        )
        return chartAlternativesLogic.findMounted({ embedded: false, ...insightProps })!
    }

    function currentTrendsQuery(): TrendsQuery {
        return (builtInsightDataLogic.values.query as InsightVizNode).source as TrendsQuery
    }

    it('applies the display rewrite when a chart is selected and closes the gallery', () => {
        setQuery(makeTrendsQuery({ trendsFilter: { display: ChartDisplayType.ActionsLineGraph, formula: 'A / B' } }))
        const logic = alternativesLogic()
        logic.actions.openGallery()
        expect(logic.values.galleryOpen).toBe(true)

        logic.actions.selectChart(ChartDisplayType.BoxPlot, 'gallery')

        expect(currentTrendsQuery().trendsFilter).toMatchObject({
            display: ChartDisplayType.BoxPlot,
            formula: undefined,
            formulaNodes: [],
        })
        expect(logic.values.galleryOpen).toBe(false)
    })

    it('mounts preview state with the chart control', () => {
        setQuery(makeTrendsQuery())
        alternativesLogic()

        expect(chartPreviewsLogic.findMounted({ embedded: false, ...insightProps })).not.toBeUndefined()
    })

    it('opens the gallery in a popover anchored to the chart type button', async () => {
        setQuery(makeTrendsQuery())
        const logic = alternativesLogic()
        expect(document.querySelector('[data-attr="chart-alternatives-gallery"]')).not.toBeInTheDocument()

        logic.actions.openGallery()

        await waitFor(() =>
            expect(document.querySelector('.Popover [data-attr="chart-alternatives-gallery"]')).toBeInTheDocument()
        )
    })

    it.each([
        ['the flag is off', [], {}],
        [
            'the control variant is served',
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES],
            { [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES]: 'control' },
        ],
    ])('hides the chart switch control when %s', async (_, flags, variants) => {
        setQuery(makeTrendsQuery())
        alternativesLogic()
        await waitFor(() => expect(document.querySelector('[data-attr="chart-alternatives-all"]')).toBeInTheDocument())

        featureFlagLogic.actions.setFeatureFlags(flags, variants)
        await waitFor(() =>
            expect(document.querySelector('[data-attr="chart-alternatives-all"]')).not.toBeInTheDocument()
        )
    })

    it.each([
        ['the gallery', 'test', 'chart-alternatives-all', 1],
        ['the chart type dropdown', 'control', 'chart-filter', 1],
    ])('reports an exposure when %s opens', async (_, variant, dataAttr, expected) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES], {
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES]: variant,
        })
        setQuery(makeTrendsQuery())
        alternativesLogic()
        const capture = jest.spyOn(posthog, 'capture')

        const menuButton = await waitFor(() => {
            const button = document.querySelector(`[data-attr="${dataAttr}"]`)
            expect(button).toBeInTheDocument()
            return button!
        })
        fireEvent.click(menuButton)

        await waitFor(() =>
            expect(capture.mock.calls.filter(([event]) => event === 'insight chart type menu opened')).toHaveLength(
                expected
            )
        )
        jest.restoreAllMocks()
    })

    it('does not report an exposure when the chart type dropdown opens on a read-only insight', () => {
        setQuery(makeTrendsQuery())
        const capture = jest.spyOn(posthog, 'capture')

        chartAlternativesLogic({ embedded: true, ...insightProps }).mount()
        chartAlternativesLogic({ embedded: true, ...insightProps }).actions.reportChartMenuOpened()

        expect(capture.mock.calls.map(([event]) => event)).not.toContain('insight chart type menu opened')
        jest.restoreAllMocks()
    })

    it.each([
        ['a read-only insight', true, NodeKind.TrendsQuery],
        ['a non-trends insight', false, NodeKind.FunnelsQuery],
    ])('does not read the experiment flag for %s', (_, embedded, kind) => {
        const readFlags: string[] = []
        const featureFlags = new Proxy(
            {},
            {
                get: (_target, flag) => {
                    readFlags.push(String(flag))
                    return 'test'
                },
            }
        )
        jest.spyOn(featureFlagLogic.selectors, 'featureFlags').mockReturnValue(featureFlags)
        builtInsightVizDataLogic.actions.updateQuerySource({ ...makeTrendsQuery(), kind } as unknown as TrendsQuery)

        const logic = chartAlternativesLogic({ embedded, ...insightProps })
        logic.mount()

        expect(logic.values.canShowAlternatives).toBe(false)
        expect(readFlags).not.toContain(FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES)
        logic.unmount()
        jest.restoreAllMocks()
    })
})
