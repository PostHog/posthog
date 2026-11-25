import { anomalySeriesKeyFromSearch, withAnomalyScoresParam } from './anomalyScoresParam'

describe('withAnomalyScoresParam', () => {
    test.each([
        ['/project/1/insights/abc', undefined, '/project/1/insights/abc?anomaly_scores=true'],
        ['/project/1/insights/abc?dashboard=2', undefined, '/project/1/insights/abc?dashboard=2&anomaly_scores=true'],
        [
            '/project/1/insights/abc#q=%7B%22a%22%3F1%7D',
            undefined,
            '/project/1/insights/abc?anomaly_scores=true#q=%7B%22a%22%3F1%7D',
        ],
        [
            '/project/1/insights/abc#q=%7B%7D',
            '0a1b2c3d4e5f6789',
            '/project/1/insights/abc?anomaly_scores=true&anomaly_series=0a1b2c3d4e5f6789#q=%7B%7D',
        ],
    ])('adds the params to %s before any hash', (path, seriesKey, expected) => {
        expect(withAnomalyScoresParam(path, seriesKey)).toEqual(expected)
    })

    test.each([
        ['a hex key', '0a1b2c3d4e5f6789'],
        ['a key with only digits', '0123456789012345'],
        ['a key that reads as a number in exponent form', '1234e56789012345'],
    ])('reads %s from the link as it was written', (_name, seriesKey) => {
        const link = withAnomalyScoresParam('/project/1/insights/abc#q=%7B%7D', seriesKey)
        expect(anomalySeriesKeyFromSearch(link.slice(link.indexOf('?'), link.indexOf('#')))).toEqual(seriesKey)
    })
})
