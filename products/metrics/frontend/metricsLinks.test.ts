import { combineUrl } from 'kea-router'

import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { metricUrl, metricsUrlForService } from './metricsLinks'

describe('metricsLinks', () => {
    const paramsOf = (url: string): Record<string, any> => combineUrl(url).searchParams

    it('links to the bare metrics route when nothing is scoped', () => {
        expect(metricUrl({})).toBe('/metrics')
    })

    // The scene opens on Overview. Any link that scopes the viewer has to say so, or it applies
    // its filters to a tab the user never sees and looks broken.
    it.each([
        ['a metric name', { metricName: 'http_requests_total' }],
        ['a filter group', { filterGroup: { type: FilterLogicalOperator.And, values: [] } }],
        ['a group-by', { groupBy: ['service_name'] }],
        ['a time window', { dateFrom: '-7d' }],
    ])('opens the viewer tab for a link carrying %s', (_name, params) => {
        expect(paramsOf(metricUrl(params)).activeTab).toBe('viewer')
    })

    // Param names are the contract with metricsSceneLogic's parser. Spelling one of them
    // differently here drops it silently on restore, so pin the names, not just the values.
    it('names the metric with the param the scene reads back', () => {
        expect(paramsOf(metricUrl({ metricName: 'http_requests_total' }))).toMatchObject({
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
