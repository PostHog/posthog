import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'

import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsSamplesCreate: jest.fn(),
}))

const mockSamplesCreate = metricsSamplesCreate as jest.MockedFunction<typeof metricsSamplesCreate>

const SAMPLE = {
    timestamp: '2026-07-09T05:46:28.132600+00:00',
    metric_name: 'demo_checkout_duration_ms',
    metric_type: 'histogram',
    value: 970.97,
    count: 24,
    unit: 'ms',
    aggregation_temporality: 'cumulative',
    is_monotonic: false,
    service_name: 'checkout-demo',
    trace_id: '4EE9645D1C55A19919C83FDD657C88A4',
    span_id: 'F068A584A45A5EDA',
    attributes: { endpoint: '/api/checkout' },
    resource_attributes: { 'service.name': 'checkout-demo' },
}

describe('metricsSamplesLogic', () => {
    let logic: ReturnType<typeof metricsSamplesLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockSamplesCreate.mockReset()
        mockSamplesCreate.mockResolvedValue({ results: [SAMPLE] })
        metricsViewerLogic.mount()
        logic = metricsSamplesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        metricsViewerLogic.unmount()
    })

    // Regression: relative date strings ('-1h') sent to the API raw are a 400 —
    // the loader must resolve them to ISO timestamps before the request.
    it('activating the samples tab fetches emissions with resolved ISO dates', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)
        const [, request] = mockSamplesCreate.mock.calls[0]
        expect(request.query.metricName).toBe('demo_checkout_duration_ms')
        expect(request.query.dateFrom).toMatch(/^\d{4}-\d{2}-\d{2}T/)
        expect(logic.values.samples).toEqual([SAMPLE])
    })

    // Regression: firing the request with an empty metric name spams 400s on the
    // empty state before a metric is picked.
    it('does not call the API without a metric selected', async () => {
        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).not.toHaveBeenCalled()
        expect(logic.values.samples).toEqual([])
    })

    // Regression: samples going stale when the selected metric changes while the
    // tab is open — and conversely, needless requests while the tab is hidden.
    it('refetches on metric change only while the samples tab is active', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)

        metricsViewerLogic.actions.setMetricName('demo_checkout_requests_total')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(2)
        expect(mockSamplesCreate.mock.calls[1][1].query.metricName).toBe('demo_checkout_requests_total')

        logic.actions.setActiveTab('aggregates')
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        await expectLogic(logic).delay(10)
        expect(mockSamplesCreate).toHaveBeenCalledTimes(2)
    })
})
