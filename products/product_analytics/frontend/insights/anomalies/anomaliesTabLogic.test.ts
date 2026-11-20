import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AnomalySearchResponseApi, AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { ANOMALIES_PAGE_SIZE, anomaliesTabLogic } from './anomaliesTabLogic'

const SEARCH_URL = '/api/projects/:team_id/signals/anomalies/search/'
const TOTAL_ROWS = ANOMALIES_PAGE_SIZE + 5

// The rows of the second page belong to insights the first page already listed, like the other values of a breakdown.
function makeSeries(index: number): AnomalySeriesApi {
    const insightId = index % ANOMALIES_PAGE_SIZE
    return {
        insight_id: insightId,
        insight_name: `Insight ${insightId}`,
        insight_url: `http://localhost/project/997/insights/short${insightId}`,
        series_key: `series-${index}`,
        series_label: 'Pageviews',
        breakdown_value: null,
        interval: 'day',
        scored_buckets: 14,
        flagged_buckets: 1,
        anomaly_rate: 1 / 14,
        expected_buckets: 14,
        coverage: 1,
        scored_through: '2026-11-16T00:00:00+00:00',
        first_flagged_bucket: '2026-11-15T00:00:00+00:00',
        last_flagged_bucket: '2026-11-15T00:00:00+00:00',
        flagged_points: [],
        dashboards: [],
        points: [],
    }
}

// Serves a ranked list of rows, one page per request, the way the anomaly search pages them.
function searchPage(offset: number, limit: number): AnomalySearchResponseApi {
    const rows = Array.from({ length: TOTAL_ROWS }, (_, index) => makeSeries(index))
    return {
        scoring_enabled: true,
        watched_insights: 80,
        insights_scored_in_range: 70,
        scored_days: 28,
        scored_history_ready: true,
        date_from: '2026-11-03T00:00:00+00:00',
        date_to: '2026-11-17T00:00:00+00:00',
        group_by: 'series',
        order: 'recent',
        series: rows.slice(offset, offset + limit),
        insights: [],
        has_more: offset + limit < TOTAL_ROWS,
        truncated: false,
        message: null,
    }
}

describe('anomaliesTabLogic', () => {
    let logic: ReturnType<typeof anomaliesTabLogic.build>
    let status: number

    beforeEach(() => {
        status = 200
        useMocks({
            get: {
                [SEARCH_URL]: ({ request }) => {
                    if (status !== 200) {
                        return [status, { detail: 'Not found.' }]
                    }
                    const params = new URL(request.url).searchParams
                    return [200, searchPage(Number(params.get('offset')), Number(params.get('limit')))]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('appends the next page and groups its series under the insights already shown', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.series).toHaveLength(ANOMALIES_PAGE_SIZE)
        expect(logic.values.insightGroups).toHaveLength(ANOMALIES_PAGE_SIZE)
        expect(logic.values.hasMore).toBe(true)

        logic.actions.loadMoreAnomalies()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.series.map((row) => row.series_key)).toEqual(
            Array.from({ length: TOTAL_ROWS }, (_, index) => `series-${index}`)
        )
        expect(logic.values.insightGroups.map((group) => group.insightId)).toEqual(
            Array.from({ length: ANOMALIES_PAGE_SIZE }, (_, index) => index)
        )
        expect(logic.values.insightGroups[0].series.map((row) => row.series_key)).toEqual([
            'series-0',
            `series-${ANOMALIES_PAGE_SIZE}`,
        ])
        expect(logic.values.hasMore).toBe(false)
    })

    it('collapses expanded insights when the filters change', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.toggleInsightExpanded(0, 0)
        expect(logic.values.expandedInsightIds).toEqual({ 0: true })

        logic.actions.setFilters({ dateFrom: '-30d' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.expandedInsightIds).toEqual({})
    })

    it('captures a rating once per change and keeps it for the flagged bucket it judged', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const row = logic.values.series[0]
        const ratedEvents = (): unknown[] =>
            capture.mock.calls.filter(([event]) => event === 'anomalies tab series rated').map(([, props]) => props)

        logic.actions.rateSeries(row, 'useful', 0)
        logic.actions.rateSeries(row, 'useful', 0)
        logic.actions.rateSeries(row, 'not_useful', 0)
        logic.actions.rateSeries({ ...row, last_flagged_bucket: '2026-11-16T00:00:00+00:00' }, 'useful', 0)

        expect(ratedEvents()).toEqual([
            expect.objectContaining({
                rating: 'useful',
                insight_id: row.insight_id,
                series_key: row.series_key,
                flagged_bucket: row.last_flagged_bucket,
            }),
            expect.objectContaining({ rating: 'not_useful', flagged_bucket: row.last_flagged_bucket }),
            expect.objectContaining({ rating: 'useful', flagged_bucket: '2026-11-16T00:00:00+00:00' }),
        ])
        expect(Object.values(logic.values.seriesRatings)).toEqual(['not_useful', 'useful'])
    })

    it('shows the not available state when the search answers 404', async () => {
        status = 404
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadError).toEqual('not_available')
        expect(logic.values.anomalies).toBeNull()
    })
})
