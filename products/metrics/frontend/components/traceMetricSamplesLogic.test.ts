import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'

import { traceMetricSamplesLogic } from './traceMetricSamplesLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsSamplesCreate: jest.fn(),
}))

const mockSamplesCreate = metricsSamplesCreate as jest.MockedFunction<typeof metricsSamplesCreate>

const TRACE_ID = '4EE9645D1C55A19919C83FDD657C88A4'

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
    trace_id: TRACE_ID,
    span_id: 'F068A584A45A5EDA',
    attributes: { endpoint: '/api/checkout' },
    resource_attributes: { 'service.name': 'checkout-demo' },
}

const PROPS = {
    traceId: TRACE_ID,
    dateFrom: '2026-07-09T04:46:28.000Z',
    dateTo: '2026-07-09T06:46:28.000Z',
}

describe('traceMetricSamplesLogic', () => {
    let logic: ReturnType<typeof traceMetricSamplesLogic.build>

    const grantMetricsAccess = (level: AccessControlLevel | null): void => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: level,
            },
        } as AppContext
    }

    beforeEach(() => {
        grantMetricsAccess(AccessControlLevel.Viewer)
        initKeaTests()
        mockSamplesCreate.mockReset()
        mockSamplesCreate.mockResolvedValue({ results: [SAMPLE] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The trace->metrics pivot: the request names the trace and omits metricName, so the
    // response spans every metric the trace touched. A metricName sneaking in would
    // silently narrow the tab to one metric.
    it('loads emissions for the trace on mount, without a metric name', async () => {
        logic = traceMetricSamplesLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)
        const [, request] = mockSamplesCreate.mock.calls[0]
        expect(request.query.traceId).toBe(TRACE_ID)
        expect(request.query).not.toHaveProperty('metricName')
        expect(request.query).not.toHaveProperty('spanId')
        expect(request.query.dateFrom).toBe(PROPS.dateFrom)
        expect(logic.values.samples).toEqual([SAMPLE])
    })

    // Span scope narrows server-side, so the result stays exact even when the trace has
    // more emissions than the request limit — a client-side filter over a capped response
    // would silently show "no metrics" for spans outside the newest page.
    it('passes the span id through to the request in span scope', async () => {
        logic = traceMetricSamplesLogic({ ...PROPS, spanId: SAMPLE.span_id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        const [, request] = mockSamplesCreate.mock.calls[0]
        expect(request.query.spanId).toBe(SAMPLE.span_id)
    })

    it('skips the request without metrics view access', async () => {
        grantMetricsAccess(null)

        logic = traceMetricSamplesLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).not.toHaveBeenCalled()
        expect(logic.values.samples).toEqual([])
    })

    it('flags the error state when the request fails', async () => {
        mockSamplesCreate.mockRejectedValue(new Error('boom'))

        logic = traceMetricSamplesLogic(PROPS)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSamplesFailure'])

        expect(logic.values.samplesError).toBe(true)
    })
})
