import { combineUrl } from 'kea-router'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { metricUrl, metricsUrlForService } from './metricsLinks'

describe('metricsLinks', () => {
    const paramsOf = (url: string): Record<string, any> => combineUrl(url).searchParams

    it('links to the bare metrics route when nothing is scoped', () => {
        expect(metricUrl({})).toBe('/metrics')
    })

    it('opens the viewer tab whenever a metric is named, so the link lands on the chart', () => {
        // The scene defaults to Overview. A link to a metric that dropped the user on Overview
        // would look broken.
        expect(paramsOf(metricUrl({ metricName: 'http_requests_total' }))).toMatchObject({
            activeTab: 'viewer',
            metricName: 'http_requests_total',
        })
    })

    it('carries the metric type and aggregation so the link charts exactly one series shape', () => {
        expect(
            paramsOf(metricUrl({ metricName: 'http_requests_total', metricType: 'sum', aggregation: 'rate' }))
        ).toMatchObject({ metricType: 'sum', aggregation: 'rate' })
    })

    it('carries the time window', () => {
        expect(paramsOf(metricUrl({ dateFrom: '-7d', dateTo: '-1d' }))).toMatchObject({
            dateFrom: '-7d',
            dateTo: '-1d',
        })
    })

    it('serializes the filter group as JSON the scene can parse back', () => {
        const url = metricsUrlForService('checkout', {})
        expect(JSON.parse(paramsOf(url).filterGroup)).toEqual({
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: PropertyFilterType.MetricAttribute,
                            key: 'service_name',
                            value: ['checkout'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
        })
    })

    it('scopes a service link to the window the caller was looking at', () => {
        expect(paramsOf(metricsUrlForService('checkout', { dateFrom: '-30m', dateTo: null }))).toMatchObject({
            dateFrom: '-30m',
        })
    })
})
