import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AppContext,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
    UniversalFiltersGroupValue,
} from '~/types'

import { metricsErrorSpikesRetrieve, metricsSamplesCreate } from 'products/metrics/frontend/generated/api'

import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsSamplesCreate: jest.fn(),
    metricsErrorSpikesRetrieve: jest.fn(),
}))

const mockSamplesCreate = metricsSamplesCreate as jest.MockedFunction<typeof metricsSamplesCreate>
const mockErrorSpikesRetrieve = metricsErrorSpikesRetrieve as jest.MockedFunction<typeof metricsErrorSpikesRetrieve>

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

const filterGroupWith = (filters: Record<string, any>[]): UniversalFiltersGroup => ({
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: filters.map(
                (filter) => ({ type: PropertyFilterType.MetricAttribute, ...filter }) as UniversalFiltersGroupValue
            ),
        },
    ],
})

const UNTRACED_SAMPLE = {
    ...SAMPLE,
    timestamp: '2026-07-09T05:47:28.132600+00:00',
    value: 12.5,
    trace_id: '',
    span_id: '',
}

const ERROR_SPIKE = {
    detected_at: '2026-07-09T05:46:00.000000+00:00',
    issue_id: '0198e2b1-0000-7000-8000-000000000001',
    issue_name: 'NullPointerException',
}

describe('metricsSamplesLogic', () => {
    let logic: ReturnType<typeof metricsSamplesLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
                // The error-spikes loader also requires Error Tracking view access.
                [AccessControlResourceType.ErrorTracking]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        mockSamplesCreate.mockReset()
        mockSamplesCreate.mockResolvedValue({ results: [SAMPLE] })
        mockErrorSpikesRetrieve.mockReset()
        mockErrorSpikesRetrieve.mockResolvedValue({ results: [ERROR_SPIKE] })
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
        expect(logic.values.samples).toEqual([{ ...SAMPLE, clauses: ['a'] }])
    })

    // Regression: firing the request with an empty metric name spams 400s on the
    // empty state before a metric is picked.
    it('does not call the API without a metric selected', async () => {
        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).not.toHaveBeenCalled()
        expect(logic.values.samples).toEqual([])
    })

    it('does not call the API without metrics viewer access', async () => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.None,
            },
        } as AppContext
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

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

    // Regression: with several series the panel listed only the focused clause's emissions,
    // so the samples and the chart's exemplar dots did not match what the chart draws.
    it('merges the emissions of every series, newest first', async () => {
        const otherSample = {
            ...SAMPLE,
            metric_name: 'demo_checkout_errors_total',
            timestamp: '2026-07-09T05:50:00+00:00',
        }
        mockSamplesCreate.mockImplementation(async (_, { query }) => ({
            results: query.metricName === 'demo_checkout_errors_total' ? [otherSample] : [SAMPLE],
        }))
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        metricsViewerLogic.actions.addClause()
        metricsViewerLogic.actions.setMetricName('demo_checkout_errors_total')
        metricsViewerLogic.actions.duplicateClause(1)

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).toHaveBeenCalledTimes(2)
        expect(logic.values.samples).toEqual([
            { ...otherSample, clauses: ['b', 'c'] },
            { ...SAMPLE, clauses: ['a'] },
        ])
    })

    it('shows the series that loaded when another series fails', async () => {
        mockSamplesCreate.mockImplementation(async (_, { query }) => {
            if (query.metricName === 'demo_checkout_errors_total') {
                throw new Error('timeout')
            }
            return { results: [SAMPLE] }
        })
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        metricsViewerLogic.actions.addClause()
        metricsViewerLogic.actions.setMetricName('demo_checkout_errors_total')

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(logic.values.samples).toEqual([{ ...SAMPLE, clauses: ['a'] }])
        expect(logic.values.failedSampleClauses).toEqual(['b'])
    })

    // Regression: the panel listing emissions the chart above it excludes, because
    // the request went out with only the metric name and date range.
    it('scopes the request to the viewer filter bar and the picked metric type', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        metricsViewerLogic.actions.setSelectedMetricType('histogram')
        metricsViewerLogic.actions.setFilterGroup(
            filterGroupWith([{ key: 'env', operator: PropertyOperator.Exact, value: ['prod'] }])
        )

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        const [, request] = mockSamplesCreate.mock.calls[0]
        expect(request.query.filters).toEqual([{ key: 'env', op: 'eq', value: 'prod' }])
        expect(request.query.metricType).toBe('histogram')
    })

    // Regression: samples going stale when a filter changes while the tab is open,
    // and conversely needless requests while the tab is hidden.
    it('refetches on filter change only while the samples tab is active', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)

        metricsViewerLogic.actions.setFilterGroup(
            filterGroupWith([{ key: 'env', operator: PropertyOperator.Exact, value: ['prod'] }])
        )
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(2)
        expect(mockSamplesCreate.mock.calls[1][1].query.filters).toEqual([{ key: 'env', op: 'eq', value: 'prod' }])

        logic.actions.setActiveTab('aggregates')
        metricsViewerLogic.actions.setFilterGroup(
            filterGroupWith([{ key: 'env', operator: PropertyOperator.Exact, value: ['dev'] }])
        )
        await expectLogic(logic).delay(10)
        expect(mockSamplesCreate).toHaveBeenCalledTimes(2)
    })

    // Regression: exemplar dots on the chart silently vanish if untraced emissions
    // leak into (or traced ones are dropped from) the derived exemplar list.
    it('derives traceExemplars from traced samples only', async () => {
        mockSamplesCreate.mockResolvedValue({ results: [SAMPLE, UNTRACED_SAMPLE] })
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(logic.values.traceExemplars).toEqual([
            {
                timestamp: SAMPLE.timestamp,
                value: SAMPLE.value,
                traceId: SAMPLE.trace_id,
                spanId: SAMPLE.span_id,
            },
        ])
    })

    // Regression: the chart's exemplar overlay starves (never fetches samples)
    // unless the samples tab happens to be open — a chart redraw must refresh them.
    it('refreshes samples on chart query success', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)
    })

    // Regression: an always-on error-spikes fetch would spam Error Tracking on
    // every chart redraw for every metrics viewer, whether or not the overlay is
    // visible — the toggle must gate the request, not just the chart markers.
    // Regression: every auto-refresh tick sent one samples request per series while nobody looked at them.
    it('skips the samples reload on an unchanged chart query while the tab is hidden', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)

        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).delay(400)
        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)

        logic.actions.setActiveTab('samples')
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])
        expect(mockSamplesCreate).toHaveBeenCalledTimes(3)
    })

    // Regression: a slow request for the old metric stored the new metric's key, so the new chart never got samples.
    it('loads samples for a metric picked while the previous request was in flight', async () => {
        let release: () => void = () => undefined
        mockSamplesCreate.mockImplementationOnce(
            () => new Promise((resolve) => (release = () => resolve({ results: [SAMPLE] })))
        )
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).delay(400)

        metricsViewerLogic.actions.setMetricName('demo_checkout_requests_total')
        release()
        await expectLogic(logic).delay(10)
        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).delay(400)

        expect(mockSamplesCreate.mock.calls.map(([, { query }]) => query.metricName)).toEqual([
            'demo_checkout_duration_ms',
            'demo_checkout_requests_total',
        ])
    })

    // Regression: with the tab open, each auto-refresh restarted a slow batch, so it never finished.
    it('lets a running samples batch finish when the chart refreshes', async () => {
        let release: () => void = () => undefined
        mockSamplesCreate.mockImplementationOnce(
            () => new Promise((resolve) => (release = () => resolve({ results: [SAMPLE] })))
        )
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')
        logic.actions.setActiveTab('samples')
        await expectLogic(logic).delay(400)

        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).delay(400)
        release()
        await expectLogic(logic).toDispatchActions(['loadSamplesSuccess'])

        expect(mockSamplesCreate).toHaveBeenCalledTimes(1)
        expect(logic.values.samples).toEqual([{ ...SAMPLE, clauses: ['a'] }])
    })

    it('does not fetch error spikes until the toggle is enabled', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).delay(10)

        expect(mockErrorSpikesRetrieve).not.toHaveBeenCalled()
        expect(logic.values.errorSpikes).toEqual([])
    })

    // Regression: toggling on must actually fetch immediately, and the chart's
    // ongoing refresh trigger must keep firing it afterwards — the overlay
    // otherwise silently shows stale (or no) spikes once enabled.
    it('fetches error spikes once the toggle is enabled', async () => {
        metricsViewerLogic.actions.setMetricName('demo_checkout_duration_ms')

        logic.actions.toggleShowErrorSpikes()
        await expectLogic(logic).toDispatchActions(['loadErrorSpikesSuccess'])
        expect(mockErrorSpikesRetrieve).toHaveBeenCalledTimes(1)
        expect(logic.values.errorSpikes).toEqual([ERROR_SPIKE])

        metricsViewerLogic.actions.fetchQueryResultsSuccess([])
        await expectLogic(logic).toDispatchActions(['loadErrorSpikesSuccess'])
        expect(mockErrorSpikesRetrieve).toHaveBeenCalledTimes(2)
    })
})
