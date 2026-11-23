import { anomalySeriesLabel } from './anomalySeriesLabel'

describe('anomalySeriesLabel', () => {
    test.each([
        ['no breakdown', 'Pageview', null, 'Pageview'],
        ['a plain breakdown value', 'Pageview - Chrome', 'Chrome', 'Pageview - Chrome'],
        [
            'a null breakdown value after the series name',
            'Pageview - $$_posthog_breakdown_null_$$',
            '$$_posthog_breakdown_null_$$',
            'Pageview - None (i.e. no value)',
        ],
        [
            'a null breakdown value as the whole label',
            '$$_posthog_breakdown_null_$$',
            '$$_posthog_breakdown_null_$$',
            'None (i.e. no value)',
        ],
        ['a list breakdown value', 'Pageview - [10,20]', '[10,20]', 'Pageview - 10 – 20'],
        [
            'a multiple breakdown with a null part',
            'Pageview - Chrome::$$_posthog_breakdown_null_$$',
            'Chrome::$$_posthog_breakdown_null_$$',
            'Pageview - Chrome::None (i.e. no value)',
        ],
        ['an empty series label', '', '$$_posthog_breakdown_null_$$', 'None (i.e. no value)'],
        ['a label that does not end with the breakdown value', 'Renamed series', 'Chrome', 'Renamed series'],
    ])('formats %s', (_, seriesLabel, breakdownValue, expected) => {
        expect(anomalySeriesLabel({ series_label: seriesLabel, breakdown_value: breakdownValue })).toEqual(expected)
    })
})
