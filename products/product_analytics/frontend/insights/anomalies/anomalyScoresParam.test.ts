import { withAnomalyScoresParam } from './anomalyScoresParam'

describe('withAnomalyScoresParam', () => {
    test.each([
        ['/project/1/insights/abc', '/project/1/insights/abc?anomaly_scores=true'],
        ['/project/1/insights/abc?dashboard=2', '/project/1/insights/abc?dashboard=2&anomaly_scores=true'],
        [
            '/project/1/insights/abc#q=%7B%22a%22%3F1%7D',
            '/project/1/insights/abc?anomaly_scores=true#q=%7B%22a%22%3F1%7D',
        ],
    ])('adds the param to %s before any hash', (path, expected) => {
        expect(withAnomalyScoresParam(path)).toEqual(expected)
    })
})
