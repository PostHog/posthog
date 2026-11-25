import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    AnomalyPointsRequestApi,
    AnomalySearchResponseApi,
    AnomalySeriesApi,
} from 'products/signals/frontend/generated/api.schemas'

import { anomaliesDashboardPickerLogic } from './anomaliesDashboardPickerLogic'
import {
    ANOMALIES_PAGE_SIZE,
    CHART_POINTS_MAX_ATTEMPTS,
    CHART_POINTS_RETRY_DELAY_MS,
    anomaliesTabLogic,
    anomalySeriesKey,
} from './anomaliesTabLogic'

const SEARCH_URL = '/api/projects/:team_id/signals/anomalies/search/'
const POINTS_URL = '/api/projects/:team_id/signals/anomalies/points/'
const DASHBOARDS_URL = '/api/projects/:team_id/dashboards/'
const POINTS_DATE_TO = '2026-11-17T00:00:00+00:00'
const POINT = { bucket_start: '2026-11-15T00:00:00+00:00', value: 42, flag: true }
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
        interval_ranges: [],
        group_by: 'series',
        order: 'recent',
        series: rows.slice(offset, offset + limit),
        insights: [],
        has_more: offset + limit < TOTAL_ROWS,
        truncated: false,
        series_capped: false,
        message: null,
        scored_through: '2026-11-16T00:00:00+00:00',
        viewed_within_days: 30,
        viewed_scope_empty: false,
    }
}

describe('anomaliesTabLogic', () => {
    let logic: ReturnType<typeof anomaliesTabLogic.build>
    let status: number
    let pointsStatus: number
    let searchRequests: URLSearchParams[]
    let pointsRequests: AnomalyPointsRequestApi[]
    let dashboardSearches: (string | null)[]
    // Holds back the response of the first points request until the test releases it.
    let holdFirstPoints: boolean
    let releaseFirstPoints: () => void

    beforeEach(() => {
        status = 200
        pointsStatus = 200
        searchRequests = []
        pointsRequests = []
        dashboardSearches = []
        holdFirstPoints = false
        releaseFirstPoints = () => {}
        useMocks({
            get: {
                [SEARCH_URL]: ({ request }) => {
                    if (status !== 200) {
                        return [status, { detail: 'Not found.' }]
                    }
                    const params = new URL(request.url).searchParams
                    searchRequests.push(params)
                    return [200, searchPage(Number(params.get('offset')), Number(params.get('limit')))]
                },
                [DASHBOARDS_URL]: ({ request }) => {
                    dashboardSearches.push(new URL(request.url).searchParams.get('search'))
                    return [200, { count: 1, next: null, previous: null, results: [{ id: 1, name: 'Growth' }] }]
                },
            },
            post: {
                [POINTS_URL]: async ({ request }) => {
                    const body = (await request.json()) as AnomalyPointsRequestApi
                    pointsRequests.push(body)
                    const requestNumber = pointsRequests.length
                    if (requestNumber === 1 && holdFirstPoints) {
                        await new Promise<void>((resolve) => {
                            releaseFirstPoints = resolve
                        })
                    }
                    if (pointsStatus !== 200) {
                        return [pointsStatus, { detail: 'Server error.' }]
                    }
                    // The API leaves out a series the user cannot read, here insight 0.
                    const series = body.series
                        .filter((ref) => ref.insight_id !== 0)
                        .map((ref) => ({
                            ...ref,
                            date_from: '2026-11-03T00:00:00+00:00',
                            points: [{ ...POINT, value: requestNumber }],
                        }))
                    return [200, { date_to: POINTS_DATE_TO, series }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    it('appends the next page after the series already shown', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.series).toHaveLength(ANOMALIES_PAGE_SIZE)
        expect(logic.values.hasMore).toBe(true)

        logic.actions.loadMoreAnomalies()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.series.map((row) => row.series_key)).toEqual(
            Array.from({ length: TOTAL_ROWS }, (_, index) => `series-${index}`)
        )
        expect(logic.values.hasMore).toBe(false)
    })

    it('loads the list without points, then the chart points of each page', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.loadMoreAnomalies()
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests.map((params) => params.get('include_points'))).toEqual(['false', 'false'])
        expect(pointsRequests.map((body) => body.series[0].series_key)).toEqual([
            'series-0',
            `series-${ANOMALIES_PAGE_SIZE}`,
        ])
        expect(pointsRequests.map((body) => body.series.length)).toEqual([
            ANOMALIES_PAGE_SIZE,
            TOTAL_ROWS - ANOMALIES_PAGE_SIZE,
        ])
        const [unreadable, readable] = logic.values.series
        expect(logic.values.chartPoints[anomalySeriesKey(unreadable)]).toEqual({
            chartFrom: POINTS_DATE_TO,
            points: [],
        })
        expect(logic.values.chartPoints[anomalySeriesKey(readable)]).toEqual({
            chartFrom: '2026-11-03T00:00:00+00:00',
            points: [{ ...POINT, value: 1 }],
        })
        expect(logic.values.chartPointsStatus).toEqual({})
    })

    it('ignores chart points that arrive after a filter change replaced their list', async () => {
        holdFirstPoints = true
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadAnomaliesSuccess', 'loadChartPoints'])

        logic.actions.setFilters({ dateFrom: '-30d' })
        await expectLogic(logic).toDispatchActions(['loadAnomaliesSuccess', 'setChartPoints'])
        releaseFirstPoints()
        await expectLogic(logic).toFinishAllListeners()

        expect(pointsRequests).toHaveLength(2)
        const readable = logic.values.series[1]
        expect(logic.values.chartPoints[anomalySeriesKey(readable)].points).toEqual([{ ...POINT, value: 2 }])
        expect(logic.values.chartPointsStatus).toEqual({})
    })

    it('retries a failed chart batch a limited number of times and does not retry it for the next page', async () => {
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        pointsStatus = 500
        const settleRetries = async (): Promise<void> => {
            for (let attempt = 1; attempt < CHART_POINTS_MAX_ATTEMPTS; attempt++) {
                await jest.advanceTimersByTimeAsync(CHART_POINTS_RETRY_DELAY_MS * 2 ** attempt)
            }
            await expectLogic(logic).toFinishAllListeners()
        }
        logic = anomaliesTabLogic()
        logic.mount()
        await settleRetries()

        expect(logic.values.series).toHaveLength(ANOMALIES_PAGE_SIZE)
        expect(logic.values.chartPoints).toEqual({})
        expect(new Set(Object.values(logic.values.chartPointsStatus))).toEqual(new Set(['failed']))
        expect(Object.keys(logic.values.chartPointsStatus)).toHaveLength(ANOMALIES_PAGE_SIZE)

        logic.actions.loadMoreAnomalies()
        await settleRetries()

        expect(pointsRequests.map((body) => [body.series[0].series_key, body.series.length])).toEqual([
            ...Array(CHART_POINTS_MAX_ATTEMPTS).fill(['series-0', ANOMALIES_PAGE_SIZE]),
            ...Array(CHART_POINTS_MAX_ATTEMPTS).fill([
                `series-${ANOMALIES_PAGE_SIZE}`,
                TOTAL_ROWS - ANOMALIES_PAGE_SIZE,
            ]),
        ])
        expect(Object.keys(logic.values.chartPointsStatus)).toHaveLength(TOTAL_ROWS)
    })

    it('loads dashboards only when the picker opens, and searches them on the server', async () => {
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(dashboardSearches).toEqual([])

        const picker = anomaliesDashboardPickerLogic()
        picker.mount()
        picker.actions.ensureOptionsLoaded()
        await expectLogic(picker).toFinishAllListeners()
        picker.actions.setSearch('growth')
        await expectLogic(picker).toDispatchActions(['loadOptionsSuccess', 'loadOptionsSuccess'])

        expect(dashboardSearches).toEqual([null, 'growth'])
        expect(picker.values.dashboardOptions.map((dashboard) => dashboard.name)).toEqual(['Growth'])
        picker.unmount()
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

    it.each([
        ['the 30-day scope without a scope in the URL', undefined, '30'],
        ['the scope in the URL', '7', '7'],
        ['the whole project', 'project', null],
        ['the 30-day scope for an unknown value', '8', '30'],
    ])('opens on %s', async (_name, param, expected) => {
        const capture = jest.spyOn(posthog, 'capture')
        router.actions.push('/insights', { tab: 'anomalies', ...(param && { anomalies_scope: param }) })
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests.map((params) => params.get('viewed_within_days'))).toEqual([expected])
        expect(capture).toHaveBeenCalledWith(
            'anomalies tab viewed',
            expect.objectContaining({ viewed_within_days: expected == null ? null : Number(expected) })
        )
    })

    it('keeps a scope change in the URL and in the filter changed event, and through clearing the filters', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        router.actions.push('/insights', { tab: 'anomalies' })
        logic = anomaliesTabLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setFilters({ viewedWithinDays: null })
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ tab: 'anomalies', anomalies_scope: 'project' })
        expect(capture).toHaveBeenLastCalledWith(
            'anomalies tab filter changed',
            expect.objectContaining({ changed: ['viewedWithinDays'], viewed_within_days: null })
        )

        logic.actions.resetFilters()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.viewedWithinDays).toBeNull()

        logic.actions.setFilters({ viewedWithinDays: 30 })
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams).toEqual({ tab: 'anomalies' })
        expect(searchRequests.map((params) => params.get('viewed_within_days'))).toEqual(['30', null, null, '30'])
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
