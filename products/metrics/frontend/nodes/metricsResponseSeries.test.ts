import { seriesFromMetricsResponse } from './metricsResponseSeries'

describe('seriesFromMetricsResponse', () => {
    const series = [{ metricName: 'logs_pii_replacements_total', labels: {}, points: [[1, 2]] }]

    it.each([
        ['a live query response (results)', { results: series }, series],
        ['a cached dashboard insight (result)', { id: 123, short_id: 'abc', result: series }, series],
        ['an insight with a null result', { id: 123, result: null }, []],
        ['no response yet', undefined, []],
        ['a response with neither key', {}, []],
    ])('reads series from %s', (_name, response, expected) => {
        expect(seriesFromMetricsResponse(response)).toEqual(expected)
    })
})
