import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import {
    metricsQueryCreate,
    metricsSamplesCreate,
    metricsValuesRetrieve,
} from 'products/metrics/frontend/generated/api'
import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { metricsSceneLogic } from '../metricsSceneLogic'
import { metricNamePickerLogic } from './metricNamePickerLogic'
import { metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { metricsViewerLogic, NEW_QUERY_STARTED_ERROR_MESSAGE } from './metricsViewerLogic'

jest.mock('posthog-js')

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
    metricsSamplesCreate: jest.fn(),
    metricsCharacterizeCreate: jest.fn(),
}))

// Sentinel strings that stand in for customer data — no capture call may ever contain them.
const SECRET_METRIC = 'customer_secret_metric'
const SECRET_LABEL = 'customer-secret-service'
const SECRET_ATTR_VALUE = 'customer-secret-endpoint'

const SAMPLE: _MetricEventSampleApi = {
    timestamp: '2026-07-09T05:46:28.132600+00:00',
    metric_name: SECRET_METRIC,
    metric_type: 'histogram',
    value: 970.97,
    count: 24,
    unit: 'ms',
    aggregation_temporality: 'cumulative',
    is_monotonic: false,
    service_name: SECRET_LABEL,
    trace_id: '4EE9645D1C55A19919C83FDD657C88A4',
    span_id: 'F068A584A45A5EDA',
    attributes: { endpoint: SECRET_ATTR_VALUE },
    resource_attributes: { 'service.name': SECRET_LABEL },
}

const TRACELESS_SAMPLE = { ...SAMPLE, trace_id: '', span_id: '', attributes: {}, resource_attributes: {} }

const captures = (event: string): any[][] =>
    (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === event)

const allCapturedProperties = (): string => JSON.stringify((posthog.capture as jest.Mock).mock.calls)

describe('metricsUsageTrackingLogic', () => {
    let logic: ReturnType<typeof metricsUsageTrackingLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.mocked(posthog.capture).mockClear()
        jest.mocked(metricsValuesRetrieve).mockReset().mockResolvedValue({ results: [] })
        jest.mocked(metricsQueryCreate).mockReset().mockResolvedValue({ results: [] })
        jest.mocked(metricsSamplesCreate).mockReset().mockResolvedValue({ results: [] })
        logic = metricsUsageTrackingLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    // The whole point of this logic is the action -> event mapping; a renamed or disconnected
    // source action silently kills the dashboard tile that reads the event.
    it.each([
        ['metrics tab changed', () => metricsSceneLogic.actions.setActiveTab('sql'), { tab: 'sql' }],
        [
            'metrics viewer aggregation changed',
            () => metricsViewerLogic.actions.setAggregation('p95'),
            { aggregation: 'p95' },
        ],
        [
            'metrics viewer view mode changed',
            () => metricsViewerLogic.actions.setViewMode('stat'),
            { view_mode: 'stat' },
        ],
        [
            'metrics viewer stat summary changed',
            () => metricsViewerLogic.actions.setStatSummary('total'),
            { stat_summary: 'total' },
        ],
        ['metrics viewer live toggled', () => metricsViewerLogic.actions.setLiveRefresh(true), { enabled: true }],
        [
            'metrics viewer date range changed',
            () => metricsViewerLogic.actions.setDateFrom('-24h'),
            { date_from: '-24h' },
        ],
        [
            'metrics viewer group by changed',
            () => metricsViewerLogic.actions.setGroupByKeys(['service.name', 'env']),
            { group_by_count: 2 },
        ],
        [
            'metrics samples panel tab changed',
            () => metricsSamplesLogic.actions.setActiveTab('samples'),
            { tab: 'samples' },
        ],
        ['metrics add to dashboard clicked', () => metricsViewerLogic.actions.addToDashboard(), { aggregation: 'sum' }],
        [
            // Reports the aggregation persisted on the insight, not the viewer's
            // current one — those diverge when the user changes the aggregation
            // while the save request is in flight (viewer state here is 'sum').
            'metrics insight saved',
            () =>
                metricsViewerLogic.actions.saveAsInsightSuccess(
                    {
                        short_id: 'abc123',
                        query: { kind: 'MetricsQuery', clauses: [{ name: 'a', aggregation: 'quantile' }] },
                    } as any,
                    {} as any
                ),
            { aggregation: 'p95' },
        ],
    ])('%s fires with enum/count properties only', (event, dispatch, expectedProperties) => {
        dispatch()
        expect(captures(event)).toEqual([[event, expectedProperties]])
    })

    it('filter changes report the applied filter count, never keys or values', () => {
        metricsViewerLogic.actions.setFilterGroup({
            type: 'AND',
            values: [
                {
                    type: 'AND',
                    values: [
                        { type: 'metric_attribute', key: 'endpoint', operator: 'exact', value: [SECRET_ATTR_VALUE] },
                    ],
                },
            ],
        } as any)
        expect(captures('metrics viewer attribute filter changed')).toEqual([
            ['metrics viewer attribute filter changed', { filter_count: 1 }],
        ])
        expect(allCapturedProperties()).not.toContain(SECRET_ATTR_VALUE)
    })

    it('selecting a metric fires without the metric name; clearing it fires nothing', () => {
        metricsViewerLogic.actions.setMetricName(SECRET_METRIC)
        expect(captures('metrics viewer metric selected')).toHaveLength(1)
        expect(allCapturedProperties()).not.toContain(SECRET_METRIC)

        metricsViewerLogic.actions.setMetricName('')
        expect(captures('metrics viewer metric selected')).toHaveLength(1)
    })

    // Selecting a metric auto-applies its recommended aggregation; counting that dispatch as a
    // user action would inflate the feature-adoption tile on every metric switch.
    it('the auto-applied recommended aggregation is not an aggregation change', () => {
        metricNamePickerLogic.actions.loadItemsSuccess([{ name: SECRET_METRIC, metric_type: 'sum' }] as any)
        metricsViewerLogic.actions.setMetricName(SECRET_METRIC)
        expect(metricsViewerLogic.values.aggregation).toBe('increase')
        expect(captures('metrics viewer aggregation changed')).toHaveLength(0)
    })

    it('query completed reports shape counts and timing, never series labels', async () => {
        jest.mocked(metricsQueryCreate).mockResolvedValue({
            results: [
                {
                    labels: { 'service.name': SECRET_LABEL },
                    points: [
                        { time: '2026-07-09T00:00:00Z', value: 1 },
                        { time: '2026-07-09T00:01:00Z', value: 2 },
                    ],
                },
                { labels: {}, points: [{ time: '2026-07-09T00:00:00Z', value: 3 }] },
            ],
        } as any)
        metricsViewerLogic.actions.setMetricName(SECRET_METRIC)
        metricsViewerLogic.actions.fetchQueryResults({})
        await expectLogic(metricsViewerLogic).toDispatchActions(['fetchQueryResultsSuccess'])

        expect(captures('metrics query completed')).toEqual([
            [
                'metrics query completed',
                {
                    series_count: 2,
                    point_count: 3,
                    load_ms: expect.any(Number),
                    aggregation: 'sum',
                    has_group_by: false,
                    has_filters: false,
                },
            ],
        ])
        expect(allCapturedProperties()).not.toContain(SECRET_LABEL)
    })

    // The loader dispatches a success with [] before any metric is picked (initial mount) —
    // counting those would swamp the query-health tiles with empty no-op "queries".
    it('the empty-name initial query success is not a completed query', async () => {
        metricsViewerLogic.actions.fetchQueryResults({})
        await expectLogic(metricsViewerLogic).toDispatchActions(['fetchQueryResultsSuccess'])
        expect(captures('metrics query completed')).toHaveLength(0)
    })

    it('query failed captures a status class, never the error message', () => {
        metricsViewerLogic.actions.fetchQueryResultsFailure(`Invalid regex in ${SECRET_METRIC}{`, { status: 400 })
        expect(captures('metrics query failed')).toEqual([['metrics query failed', { error_type: 'http_400' }]])
        expect(allCapturedProperties()).not.toContain(SECRET_METRIC)
    })

    it('a superseded (aborted) query is not a failure', () => {
        metricsViewerLogic.actions.fetchQueryResultsFailure(
            NEW_QUERY_STARTED_ERROR_MESSAGE,
            new DOMException(NEW_QUERY_STARTED_ERROR_MESSAGE, 'AbortError')
        )
        expect(captures('metrics query failed')).toHaveLength(0)
    })

    it('samples loaded reports count and trace coverage, never attribute values', async () => {
        jest.mocked(metricsSamplesCreate).mockResolvedValue({
            results: [SAMPLE, SAMPLE, SAMPLE, TRACELESS_SAMPLE],
        } as any)
        metricsViewerLogic.actions.setMetricName(SECRET_METRIC)
        metricsSamplesLogic.actions.setActiveTab('samples')
        await expectLogic(metricsSamplesLogic).toDispatchActions(['loadSamplesSuccess'])

        expect(captures('metrics samples loaded')).toEqual([
            ['metrics samples loaded', { sample_count: 4, trace_coverage: 75 }],
        ])
        expect(allCapturedProperties()).not.toContain(SECRET_ATTR_VALUE)
    })

    it.each([
        [
            'metrics sample row expanded',
            (sample: typeof SAMPLE) => logic.actions.sampleRowExpanded(sample),
            SAMPLE,
            { attribute_count: 2, has_trace: true },
        ],
        [
            'metrics sample row expanded',
            (sample: typeof SAMPLE) => logic.actions.sampleRowExpanded(sample),
            TRACELESS_SAMPLE,
            { attribute_count: 0, has_trace: false },
        ],
        [
            'metrics trace pivot clicked',
            (sample: typeof SAMPLE) => logic.actions.tracePivotClicked(sample),
            SAMPLE,
            { has_span_id: true },
        ],
        [
            'metrics trace pivot clicked',
            (sample: typeof SAMPLE) => logic.actions.tracePivotClicked(sample),
            TRACELESS_SAMPLE,
            { has_span_id: false },
        ],
    ])('%s reports derived booleans/counts only', (event, dispatch, sample, expectedProperties) => {
        dispatch(sample)
        expect(captures(event)).toEqual([[event, expectedProperties]])
        expect(allCapturedProperties()).not.toContain(SECRET_ATTR_VALUE)
    })
})
