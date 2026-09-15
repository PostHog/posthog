import { waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import type { TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, InsightShortId } from '~/types'

import { chartAlternativesLogic } from './chartAlternativesLogic'
import { chartPreviewsLogic } from './chartPreviewsLogic'
import type { ChartPreview } from './chartPreviewsLogic'

const insightProps = { dashboardItemId: 'chart-previews' as InsightShortId }
const logicProps = { editMode: true, embedded: false, ...insightProps }

const timeSeriesRow = {
    action: { id: '$pageview', type: 'events', order: 0, math: 'total' },
    label: '$pageview',
    data: [1, 2, 3],
    days: ['2026-01-01', '2026-01-02', '2026-01-03'],
    labels: ['1-Jan', '2-Jan', '3-Jan'],
    count: 6,
}
const totalValueRow = { ...timeSeriesRow, data: [], count: 0, aggregated_value: 6 }

function trendsQuery(display: ChartDisplayType): TrendsQuery {
    return {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        trendsFilter: { display },
    }
}

describe('chartPreviewsLogic', () => {
    let refreshModes: string[]
    let cacheHit: boolean

    beforeEach(() => {
        refreshModes = []
        cacheHit = true
        const queryMock = async ({ request }: { request: Request }): Promise<Record<string, unknown>> => {
            const body = (await request.json()) as { refresh?: string }
            refreshModes.push(body.refresh ?? '')
            return body.refresh === 'force_cache' && !cacheHit ? { cache_key: 'x' } : { results: [timeSeriesRow] }
        }
        useMocks({
            get: { '/api/environments/:team_id/insights/': { results: [{}] } },
            post: {
                '/api/environments/:team_id/query/': queryMock,
                '/api/environments/:team_id/query/:kind/': queryMock,
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES], {
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_CHART_ALTERNATIVES]: true,
        })
        insightLogic(insightProps).mount()
        insightDataLogic(insightProps).mount()
        insightVizDataLogic(insightProps).mount()
        chartAlternativesLogic(logicProps).mount()
        chartPreviewsLogic(logicProps).mount()
    })

    afterEach(() => {
        chartPreviewsLogic(logicProps).unmount()
        chartAlternativesLogic(logicProps).unmount()
    })

    function load(display: ChartDisplayType, row: Record<string, unknown>): void {
        insightVizDataLogic(insightProps).actions.updateQuerySource(trendsQuery(display))
        insightDataLogic(insightProps).actions.setInsightData({ results: [row] })
    }

    function lineTile(): ChartPreview | undefined {
        return chartPreviewsLogic(logicProps)
            .values.previewGroups.flatMap((group) => group.previews)
            .find((preview) => preview.option.display === ChartDisplayType.ActionsLineGraph)
    }

    it('asks the server cache once for the time series when only a total value is loaded', async () => {
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()
        await waitFor(() => expect(lineTile()?.response).not.toBeNull())
        expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1)

        chartAlternativesLogic(logicProps).actions.closeGallery()
        chartAlternativesLogic(logicProps).actions.openGallery()
        expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1)
    })

    it('shows no chart and does not retry after a cache miss', async () => {
        cacheHit = false
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()

        await waitFor(() => expect(chartPreviewsLogic(logicProps).values.cachedTimeSeriesLoading).toBe(false))
        await waitFor(() => expect(refreshModes).toContain('force_cache'))
        expect(lineTile()).toMatchObject({ response: null, loading: false })

        chartAlternativesLogic(logicProps).actions.closeGallery()
        chartAlternativesLogic(logicProps).actions.openGallery()
        expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1)
    })

    it('reuses the time series it saw before the chart became a total value', () => {
        load(ChartDisplayType.ActionsLineGraph, timeSeriesRow)
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()

        expect(lineTile()?.response).toMatchObject({ results: [expect.objectContaining({ data: [1, 2, 3] })] })
        expect(refreshModes).not.toContain('force_cache')
    })
})
