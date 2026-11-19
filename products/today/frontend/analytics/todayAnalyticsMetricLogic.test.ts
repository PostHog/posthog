import { expectLogic } from 'kea-test-utils'

import { pollForResults } from '~/queries/query'
import type { QueryStatus } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { insightsList } from 'products/product_analytics/frontend/generated/api'
import type { InsightApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { metricFromInsight, todayAnalyticsMetricLogic } from './todayAnalyticsMetricLogic'

jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), pollForResults: jest.fn() }))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/product_analytics/frontend/generated/api'),
    insightsList: jest.fn(),
}))

const insight = (query: unknown, result: unknown): InsightApi => ({ query, result }) as unknown as InsightApi
const trends = (trendsFilter?: Record<string, unknown>): unknown => ({
    kind: 'InsightVizNode',
    source: { kind: 'TrendsQuery', series: [], trendsFilter },
})
const SERIES = [{ count: 60, data: [10, 20, 30], labels: ['Mon', 'Tue', 'Wed'] }]

describe('metricFromInsight', () => {
    test.each([
        ['the total by default', insight(trends(), SERIES), 60],
        ['the latest point when the insight asks for it', insight(trends({ metricSummary: 'latest' }), SERIES), 30],
        ['the average when the insight asks for it', insight(trends({ metricSummary: 'average' }), SERIES), 20],
        ['no number for a funnel', insight({ kind: 'InsightVizNode', source: { kind: 'FunnelsQuery' } }, SERIES), null],
        ['no number before the first result', insight(trends(), null), null],
    ])('shows %s', (_name, given, expected) => {
        expect(metricFromInsight(given)?.value ?? null).toEqual(expected)
    })

    test.each([
        [
            'an aggregate display',
            [{ count: 0, aggregated_value: 60, data: [], compare_label: 'current' }],
            60,
            undefined,
        ],
        [
            'a comparison even when the previous series comes first',
            [
                { count: 120, data: [40, 40, 40], compare_label: 'previous' },
                { count: 60, data: [10, 20, 30], compare_label: 'current' },
            ],
            60,
            { value: -50 },
        ],
        [
            'an aggregate comparison',
            [
                { count: 0, aggregated_value: 120, data: [], compare_label: 'previous' },
                { count: 0, aggregated_value: 60, data: [], compare_label: 'current' },
            ],
            60,
            { value: -50 },
        ],
    ])('shows %s with the right change', (_name, result, expectedValue, expectedChange) => {
        const metric = metricFromInsight(insight(trends(), result))
        expect(metric?.value).toBe(expectedValue)
        expect(metric?.change).toEqual(expectedChange)
    })
})

describe('todayAnalyticsMetricLogic', () => {
    const pending: InsightApi = {
        ...insight(trends(), null),
        query_status: { id: 'query-1', complete: false, error: false },
    }
    const completed = insight(trends(), SERIES)
    const completedStatus: QueryStatus = {
        id: 'query-1',
        query_async: true,
        team_id: 997,
        complete: true,
        error: false,
        error_message: null,
        error_code: null,
    }

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
    })

    it.each(['completed', 'expired'] as const)('reads the cached result after a %s query status', async (status) => {
        let finishPoll!: () => void
        const polling = new Promise<Awaited<ReturnType<typeof pollForResults>>>((resolve, reject) => {
            finishPoll = () => (status === 'expired' ? reject({ status: 404 }) : resolve(completedStatus))
        })
        jest.mocked(pollForResults).mockReturnValue(polling)
        jest.mocked(insightsList).mockImplementation(
            async (_projectId, params) =>
                ({ results: [params?.refresh === 'async' ? pending : completed] }) as Awaited<
                    ReturnType<typeof insightsList>
                >
        )

        const logic = todayAnalyticsMetricLogic({ shortId: 'aB3dE5fG' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInsightSuccess'])
        expect(logic.values.metric).toBeNull()
        expect(insightsList).toHaveBeenCalledTimes(1)
        expect(insightsList).toHaveBeenNthCalledWith(1, expect.any(String), {
            short_id: 'aB3dE5fG',
            refresh: 'async',
        })

        const refreshed = expectLogic(logic).toDispatchActions(['setRefreshedInsight'])
        finishPoll()
        await refreshed
        expect(insightsList).toHaveBeenCalledTimes(2)
        expect(insightsList).toHaveBeenNthCalledWith(
            2,
            expect.any(String),
            { short_id: 'aB3dE5fG', refresh: 'force_cache' },
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        expect(logic.values.metric?.value).toBe(60)
        expect(logic.values.loadFailed).toBe(false)
    })

    it('aborts the poll on unmount without requesting the cache or marking failure', async () => {
        let finishPoll!: () => void
        const polling = new Promise<Awaited<ReturnType<typeof pollForResults>>>((resolve) => {
            finishPoll = () => resolve(completedStatus)
        })
        let markPollStarted!: () => void
        const pollStarted = new Promise<void>((resolve) => (markPollStarted = resolve))
        jest.mocked(pollForResults).mockImplementation(() => {
            markPollStarted()
            return polling
        })
        jest.mocked(insightsList).mockResolvedValue({ results: [pending] } as Awaited<ReturnType<typeof insightsList>>)

        const logic = todayAnalyticsMetricLogic({ shortId: 'aB3dE5fG' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInsightSuccess'])
        await pollStarted
        const signal = jest.mocked(pollForResults).mock.calls[0][1]?.signal
        expect(signal?.aborted).toBe(false)
        expect(logic.values.loadFailed).toBe(false)
        const failed = jest.spyOn(logic.actions, 'loadInsightFailure')
        const refreshed = jest.spyOn(logic.actions, 'setRefreshedInsight')
        logic.unmount()
        expect(signal?.aborted).toBe(true)

        finishPoll()
        await polling
        await Promise.resolve()
        expect(insightsList).toHaveBeenCalledTimes(1)
        expect(failed).not.toHaveBeenCalled()
        expect(refreshed).not.toHaveBeenCalled()
    })
})
