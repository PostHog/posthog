import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { metricsSamplesCreate } from 'products/metrics/frontend/generated/api'
import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsSamplesCreate: jest.fn(async () => ({ results: [] })),
    metricsQueryCreate: jest.fn(async () => ({ results: [] })),
    metricsCharacterizeCreate: jest.fn(async () => ({ direction: 'flat' })),
}))

const mockedSamplesCreate = metricsSamplesCreate as jest.Mock

const sample = (service: string): _MetricEventSampleApi => ({
    timestamp: '2026-01-01T00:00:00Z',
    metric_name: 'requests_total',
    metric_type: 'sum',
    value: 1,
    count: 1,
    unit: '',
    aggregation_temporality: 'cumulative',
    is_monotonic: true,
    service_name: service,
    trace_id: '',
    span_id: '',
    attributes: {},
    resource_attributes: {},
})

describe('metricsSamplesLogic', () => {
    let logic: ReturnType<typeof metricsSamplesLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        jest.spyOn(api.metrics, 'values').mockResolvedValue({ results: [] })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('does not query without a metric name', async () => {
        logic = metricsSamplesLogic()
        logic.mount()
        await logic.asyncActions.fetchSamples({})
        expect(mockedSamplesCreate).not.toHaveBeenCalled()
    })

    it.each([
        ['', false],
        ['abc123', true],
    ])('trace id %p in the request body: %p', async (traceId, included) => {
        logic = metricsSamplesLogic()
        logic.mount()
        logic.actions.setMetricName('requests_total')
        logic.actions.setTraceId(traceId)
        await logic.asyncActions.fetchSamples({})
        const body = mockedSamplesCreate.mock.calls.at(-1)[1].query
        expect(body.metricName).toBe('requests_total')
        expect('traceId' in body).toBe(included)
        expect(body.traceId).toBe(included ? traceId : undefined)
    })

    it('filters loaded samples by service client-side', () => {
        logic = metricsSamplesLogic()
        logic.mount()
        logic.actions.fetchSamplesSuccess([sample('web'), sample('worker'), sample('web')])
        expect(logic.values.serviceOptions).toEqual(['web', 'worker'])
        logic.actions.setServiceFilter(['worker'])
        expect(logic.values.filteredSamples.map((s) => s.service_name)).toEqual(['worker'])
        logic.actions.setServiceFilter([])
        expect(logic.values.filteredSamples).toHaveLength(3)
    })

    it('seeds the metric and date range from the viewer on first open', () => {
        const viewerLogic = metricsViewerLogic()
        viewerLogic.mount()
        viewerLogic.actions.setMetricName('queue_depth')
        viewerLogic.actions.setDateFrom('-24h')
        logic = metricsSamplesLogic()
        logic.mount()
        expect(logic.values.metricName).toBe('queue_depth')
        expect(logic.values.dateFrom).toBe('-24h')
        viewerLogic.unmount()
    })
})
