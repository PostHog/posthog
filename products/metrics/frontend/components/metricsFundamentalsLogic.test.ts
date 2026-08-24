import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { metricsExplainCreate, metricsQueryCreate } from 'products/metrics/frontend/generated/api'
import type {
    _MetricBucketDecompositionApi,
    _MetricQueryPointApi,
    _MetricQueryResponseApi,
} from 'products/metrics/frontend/generated/api.schemas'

import { metricsFundamentalsLogic } from './metricsFundamentalsLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsQueryCreate: jest.fn(),
    metricsExplainCreate: jest.fn(),
}))

const decomposition: _MetricBucketDecompositionApi = {
    metric_name: 'cache_size',
    metric_type: 'gauge',
    temporality: '',
    aggregation: 'sum',
    bucket_start: '2026-01-01T00:05:00Z',
    interval: '5m',
    temporal_reducer: 'last',
    spatial_reducer: 'sum',
    series: [],
    series_count: 0,
    sample_count: 0,
    series_truncated: false,
    rows_truncated: false,
    reference_value: 33,
    actual_value: 33,
    agrees: true,
}

const queryResponse = (points: _MetricQueryPointApi[]): _MetricQueryResponseApi => ({
    results: [{ labels: {}, points }],
})

describe('metricsFundamentalsLogic', () => {
    let logic: ReturnType<typeof metricsFundamentalsLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = { current_project: { id: 997 } } as unknown as AppContext
        initKeaTests()
        logic = metricsFundamentalsLogic()
        logic.mount()
        jest.mocked(metricsExplainCreate).mockResolvedValue({ decomposition })
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('explains the newest bucket that has a value, not the newest bucket', async () => {
        // The most recent bucket is usually still filling, so it comes back empty.
        // Explaining it would decompose nothing while looking like it worked.
        jest.mocked(metricsQueryCreate).mockResolvedValue(
            queryResponse([
                { time: '2026-01-01T00:00:00Z', value: 1 },
                { time: '2026-01-01T00:05:00Z', value: 2 },
                { time: '2026-01-01T00:10:00Z', value: null },
            ])
        )

        logic.actions.setMetricName('cache_size')
        await expectLogic(logic, () => logic.actions.runCheck()).toFinishAllListeners()

        expect(jest.mocked(metricsExplainCreate).mock.calls[0][1].query.bucketStart).toEqual('2026-01-01T00:05:00Z')
    })

    it('drops the previous result when a new check starts', async () => {
        // Otherwise the old metric's decomposition sits under the new metric's
        // name while the new one loads, and reads as its answer.
        jest.mocked(metricsQueryCreate).mockResolvedValue(queryResponse([{ time: '2026-01-01T00:00:00Z', value: 1 }]))
        logic.actions.setMetricName('cache_size')
        await expectLogic(logic, () => logic.actions.runCheck()).toFinishAllListeners()
        expect(logic.values.checkResult).not.toBeNull()

        logic.actions.setMetricName('other_metric')
        expectLogic(logic, () => logic.actions.runCheck())
        expect(logic.values.checkResult).toBeNull()
    })

    it('does not explain anything when the metric reported no values', async () => {
        jest.mocked(metricsQueryCreate).mockResolvedValue(queryResponse([]))

        logic.actions.setMetricName('cache_size')
        await expectLogic(logic, () => logic.actions.runCheck()).toFinishAllListeners()

        expect(metricsExplainCreate).not.toHaveBeenCalled()
        expect(logic.values.checkResult).toBeNull()
    })
})
