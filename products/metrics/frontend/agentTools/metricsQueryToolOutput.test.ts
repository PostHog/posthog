import type { ToolCallMessage } from 'products/posthog_ai/frontend/api/types'

import { describeMetricsQuery, extractMetricSeries } from './metricsQueryToolOutput'

function toolMessage(rawOutput: unknown, innerInput?: Record<string, unknown>): ToolCallMessage {
    return {
        id: 'call-1',
        resolvedKey: 'query-metrics',
        rawServerName: 'posthog',
        rawToolName: 'exec',
        rawInput: {},
        innerInput,
        rawOutput,
        content: [],
        status: 'completed',
    }
}

describe('metricsQueryToolOutput', () => {
    describe('extractMetricSeries', () => {
        it('maps returned series to a name, labels, and points', () => {
            const series = extractMetricSeries(
                toolMessage({
                    results: [
                        {
                            metric_name: 'http_requests_total',
                            labels: { service_name: 'api-gateway' },
                            points: [
                                { time: '2026-09-08T10:00:00Z', value: 1.5 },
                                { time: '2026-09-08T10:01:00Z', value: 2 },
                            ],
                        },
                    ],
                })
            )

            expect(series).toEqual([
                {
                    name: 'http_requests_total',
                    labels: ['service_name=api-gateway'],
                    values: [1.5, 2],
                    times: ['2026-09-08T10:00:00Z', '2026-09-08T10:01:00Z'],
                },
            ])
        })

        it('names a formula result series by its clause', () => {
            const series = extractMetricSeries(toolMessage({ results: [{ clause: 'a / b', points: [] }] }))

            expect(series?.[0]).toMatchObject({ name: 'a / b', labels: [], values: [] })
        })

        it('returns an empty array when the query matched no series', () => {
            expect(extractMetricSeries(toolMessage({ results: [] }))).toEqual([])
        })

        it('returns null when the output carries no results, so the generic card renders', () => {
            expect(extractMetricSeries(toolMessage({ error: 'metric not found' }))).toBeNull()
        })
    })

    describe('describeMetricsQuery', () => {
        it('summarizes the metric, aggregation, and window', () => {
            const subtitle = describeMetricsQuery(
                toolMessage(
                    { results: [] },
                    { query: { metricName: 'up', aggregation: 'avg', dateFrom: '2026-09-08T00:00:00Z' } }
                )
            )

            expect(subtitle).toBe('up · avg · from 2026-09-08T00:00:00Z')
        })

        it('summarizes a multi-clause query by its metrics and formula', () => {
            const subtitle = describeMetricsQuery(
                toolMessage(
                    { results: [] },
                    {
                        query: {
                            clauses: [
                                { metricName: 'errors_total', aggregation: 'increase' },
                                { metricName: 'requests_total', aggregation: 'increase' },
                            ],
                            formula: 'a / b',
                        },
                    }
                )
            )

            expect(subtitle).toBe('errors_total, requests_total · increase · formula: a / b')
        })
    })
})
