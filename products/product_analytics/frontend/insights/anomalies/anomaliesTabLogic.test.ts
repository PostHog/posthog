import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { AnomalySearchResponseApi, AnomalySeriesApi } from 'products/signals/frontend/generated/api.schemas'

import { ANOMALIES_PAGE_SIZE, anomaliesTabLogic } from './anomaliesTabLogic'

const SEARCH_URL = '/api/projects/:team_id/signals/anomalies/search/'
const TOTAL_ROWS = ANOMALIES_PAGE_SIZE + 5

function makeSeries(index: number): AnomalySeriesApi {
    return {
        insight_id: index,
        insight_name: `Insight ${index}`,
        insight_url: `http://localhost/project/997/insights/short${index}`,
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
        baseline_rate: 0,
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

    it('appends the next page after the rows already shown', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.series).toHaveLength(ANOMALIES_PAGE_SIZE)
        expect(logic.values.hasMore).toBe(true)

        logic.actions.loadMoreAnomalies()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.series.map((row) => row.insight_id)).toEqual(
            Array.from({ length: TOTAL_ROWS }, (_, index) => index)
        )
        expect(logic.values.hasMore).toBe(false)
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
