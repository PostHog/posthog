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

    beforeEach(() => {
        refreshModes = []
        const queryMock = async ({ request }: { request: Request }): Promise<Record<string, unknown>> => {
            const body = (await request.json()) as { refresh?: string }
            refreshModes.push(body.refresh ?? '')
            return { results: [timeSeriesRow], last_refresh: FIRST_REFRESH }
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

    function load(query: TrendsQuery, row: Record<string, unknown>, lastRefresh = FIRST_REFRESH): void {
        insightVizDataLogic(insightProps).actions.updateQuerySource(query)
        insightDataLogic(insightProps).actions.setInsightData({ results: [row], last_refresh: lastRefresh })
    }

    function lineTile(): ChartPreview | undefined {
        return chartPreviewsLogic(logicProps).values.previews.find(
            (preview) => preview.option.display === ChartDisplayType.ActionsLineGraph
        )
    }

    it('reuses the time series it saw before the chart became a total value, even when the total loaded later', async () => {
        load(trendsQuery(ChartDisplayType.ActionsLineGraph), timeSeriesRow)
        load(trendsQuery(ChartDisplayType.ActionsPie), totalValueRow, SECOND_REFRESH)
        chartAlternativesLogic(logicProps).actions.openGallery()

        await waitFor(() =>
            expect(lineTile()?.response).toMatchObject({ results: [expect.objectContaining({ data: [1, 2, 3] })] })
        )
    })

    it('does not reuse a time series remembered for a different query', async () => {
        load(trendsQuery(ChartDisplayType.ActionsLineGraph), timeSeriesRow)
        load({ ...trendsQuery(ChartDisplayType.ActionsPie), filterTestAccounts: true }, totalValueRow)
        chartAlternativesLogic(logicProps).actions.openGallery()

        await expectLogic(chartPreviewsLogic(logicProps)).toFinishAllListeners()
        expect(lineTile()).toMatchObject({ response: null })
    })

    it('shows no time series preview, and queries nothing, when a total value chart has none remembered', async () => {
        load(trendsQuery(ChartDisplayType.ActionsPie), totalValueRow)
        const queriesBeforeOpen = refreshModes.length
        chartAlternativesLogic(logicProps).actions.openGallery()

        await expectLogic(chartPreviewsLogic(logicProps)).toFinishAllListeners()
        expect(lineTile()).toMatchObject({ response: null })
        expect(refreshModes).toHaveLength(queriesBeforeOpen)
    })
})
