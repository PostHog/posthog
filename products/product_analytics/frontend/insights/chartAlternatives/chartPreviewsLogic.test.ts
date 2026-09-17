import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

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
const FIRST_REFRESH = '2026-01-01T00:00:00.000Z'
const SECOND_REFRESH = '2026-01-01T00:01:00.000Z'

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
    let cacheLastRefresh: string
    let deferCache: boolean
    let deferredCacheResponses: ((response: Record<string, unknown>) => void)[]

    beforeEach(() => {
        refreshModes = []
        cacheHit = true
        cacheLastRefresh = FIRST_REFRESH
        deferCache = false
        deferredCacheResponses = []
        const queryMock = async ({ request }: { request: Request }): Promise<Record<string, unknown>> => {
            const body = (await request.json()) as { refresh?: string }
            refreshModes.push(body.refresh ?? '')
            if (body.refresh !== 'force_cache') {
                return { results: [timeSeriesRow], last_refresh: FIRST_REFRESH }
            }
            if (!cacheHit) {
                return { cache_key: 'x' }
            }
            if (deferCache) {
                return new Promise((resolve) => deferredCacheResponses.push(resolve))
            }
            return { results: [timeSeriesRow], last_refresh: cacheLastRefresh }
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

    function load(display: ChartDisplayType, row: Record<string, unknown>, lastRefresh = FIRST_REFRESH): void {
        insightVizDataLogic(insightProps).actions.updateQuerySource(trendsQuery(display))
        insightDataLogic(insightProps).actions.setInsightData({ results: [row], last_refresh: lastRefresh })
    }

    function refresh(row: Record<string, unknown>, lastRefresh = FIRST_REFRESH): void {
        insightDataLogic(insightProps).actions.setInsightData({ results: [row], last_refresh: lastRefresh })
    }

    function lineTile(): ChartPreview | undefined {
        return chartPreviewsLogic(logicProps).values.previews.find(
            (preview) => preview.option.display === ChartDisplayType.ActionsLineGraph
        )
    }

    it.each(['openGallery', 'toggleGallery'] as const)(
        'asks the server cache once when a total value gallery opens through %s',
        async (openAction) => {
            load(ChartDisplayType.ActionsPie, totalValueRow)
            chartAlternativesLogic(logicProps).actions[openAction]()
            await waitFor(() => expect(lineTile()?.response).toMatchObject({ results: [timeSeriesRow] }))
            expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1)

            chartAlternativesLogic(logicProps).actions.closeGallery()
            chartAlternativesLogic(logicProps).actions[openAction]()
            expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1)
        }
    )

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

    it('retries a cache miss after the insight refreshes', async () => {
        cacheHit = false
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()
        await waitFor(() => expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1))

        cacheHit = true
        cacheLastRefresh = SECOND_REFRESH
        refresh(totalValueRow, SECOND_REFRESH)

        await waitFor(() => expect(lineTile()?.response).toMatchObject({ last_refresh: SECOND_REFRESH }))
        expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(2)
    })

    it('ignores a stale cache response that resolves after a refreshed lookup starts', async () => {
        deferCache = true
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()
        await waitFor(() => expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(1))

        refresh(totalValueRow, SECOND_REFRESH)
        await waitFor(() => expect(refreshModes.filter((mode) => mode === 'force_cache')).toHaveLength(2))

        deferredCacheResponses[1]({
            results: [{ ...timeSeriesRow, data: [4, 5, 6] }],
            last_refresh: SECOND_REFRESH,
        })
        await waitFor(() =>
            expect(lineTile()?.response).toMatchObject({ results: [expect.objectContaining({ data: [4, 5, 6] })] })
        )

        await expectLogic(chartPreviewsLogic(logicProps), () => {
            deferredCacheResponses[0]({
                results: [{ ...timeSeriesRow, data: [1, 1, 1] }],
                last_refresh: FIRST_REFRESH,
            })
        }).toFinishAllListeners()
        expect(lineTile()?.response).toMatchObject({ results: [expect.objectContaining({ data: [4, 5, 6] })] })
    })

    it.each([false, true])('rejects stale remembered and cached responses (cache hit: %s)', async (hasCacheHit) => {
        cacheHit = hasCacheHit
        load(ChartDisplayType.ActionsLineGraph, timeSeriesRow)
        await waitFor(() => expect(chartPreviewsLogic(logicProps).values.rememberedTimeSeries).not.toBeNull())
        load(ChartDisplayType.ActionsPie, totalValueRow, SECOND_REFRESH)
        chartAlternativesLogic(logicProps).actions.openGallery()

        expect(lineTile()?.response).toBeNull()
        await waitFor(() => expect(refreshModes).toContain('force_cache'))
        await waitFor(() => expect(lineTile()).toMatchObject({ response: null, loading: false }))
    })

    it('reuses the time series it saw before the chart became a total value when it is still fresh', async () => {
        load(ChartDisplayType.ActionsLineGraph, timeSeriesRow)
        await waitFor(() => expect(chartPreviewsLogic(logicProps).values.rememberedTimeSeries).not.toBeNull())
        load(ChartDisplayType.ActionsPie, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()

        await waitFor(() =>
            expect(lineTile()?.response).toMatchObject({ results: [expect.objectContaining({ data: [1, 2, 3] })] })
        )
        expect(refreshModes).not.toContain('force_cache')
    })
})
