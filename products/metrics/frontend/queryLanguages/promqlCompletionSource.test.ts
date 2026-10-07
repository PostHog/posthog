import {
    metricsAttributeValuesRetrieve,
    metricsAttributesRetrieve,
    metricsNamesRetrieve,
} from 'products/metrics/frontend/generated/api'

import { createMetricsPromQLCompletionSource } from './promqlCompletionSource'

jest.mock('products/metrics/frontend/generated/api', () => ({
    metricsNamesRetrieve: jest.fn(),
    metricsAttributesRetrieve: jest.fn(),
    metricsAttributeValuesRetrieve: jest.fn(),
}))

describe('createMetricsPromQLCompletionSource', () => {
    beforeEach(() => {
        jest.mocked(metricsNamesRetrieve).mockReset()
        jest.mocked(metricsAttributesRetrieve).mockReset()
        jest.mocked(metricsAttributeValuesRetrieve).mockReset()
    })

    it('loads metric names once and filters them while the user types', async () => {
        jest.mocked(metricsNamesRetrieve).mockResolvedValue({
            results: [
                { name: 'http.server.duration', metric_type: 'histogram' },
                { name: 'queue_depth', metric_type: 'gauge' },
            ],
        })
        const source = createMetricsPromQLCompletionSource('1')

        expect(await source.metricNames('HTTP')).toEqual([{ name: 'http.server.duration', type: 'histogram' }])
        expect(await source.metricNames('queue')).toEqual([{ name: 'queue_depth', type: 'gauge' }])
        expect(metricsNamesRetrieve).toHaveBeenCalledTimes(1)
    })

    it('asks for the labels of the histogram behind a bucket series, and adds le', async () => {
        jest.mocked(metricsAttributesRetrieve).mockResolvedValue({
            results: [
                { name: 'service.name', value_count: 2 },
                { name: 'http.route', value_count: 5 },
            ],
            count: 2,
        })
        const source = createMetricsPromQLCompletionSource('1')

        expect(await source.labelNames('http.server.duration_bucket', '')).toEqual(['service_name', 'le', 'http.route'])
        expect(metricsAttributesRetrieve).toHaveBeenCalledWith('1', { limit: 100, metricName: 'http.server.duration' })
    })

    it('does not cache a failed request', async () => {
        jest.mocked(metricsAttributeValuesRetrieve)
            .mockRejectedValueOnce(new Error('down'))
            .mockResolvedValueOnce({ results: [{ id: 'api', name: 'api', count: 3 }] })
        const source = createMetricsPromQLCompletionSource('1')

        await expect(source.labelValues('service_name', undefined, '')).rejects.toThrow('down')
        expect(await source.labelValues('service_name', undefined, '')).toEqual(['api'])
    })
})
