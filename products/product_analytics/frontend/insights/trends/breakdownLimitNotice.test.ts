import { CompareLabelType, TrendResult } from '~/types'

import { getBreakdownLimitNotice } from './breakdownLimitNotice'

const OTHER = '$$_posthog_breakdown_other_$$'

function row(breakdown_value: string, extra: Partial<TrendResult> = {}): TrendResult {
    return {
        breakdown_value,
        breakdown_event_count: 10,
        count: 0,
        data: [],
        days: [],
        label: '',
        labels: [],
        aggregated_value: 0,
        ...extra,
    }
}

describe('getBreakdownLimitNotice', () => {
    it.each([
        {
            name: 'counts each value once across formulas and compared periods',
            results: [
                row('home', { order: 0, compare_label: CompareLabelType.Current }),
                row('pricing', { order: 0, compare_label: CompareLabelType.Current }),
                row(OTHER, { order: 0, compare_label: CompareLabelType.Current, breakdown_other_values_count: 7 }),
                row('home', { order: 1, compare_label: CompareLabelType.Current }),
                row('pricing', { order: 1, compare_label: CompareLabelType.Current }),
                row(OTHER, { order: 1, compare_label: CompareLabelType.Current, breakdown_other_values_count: 7 }),
                row('home', { order: 0, compare_label: CompareLabelType.Previous }),
                row('docs', { order: 0, compare_label: CompareLabelType.Previous }),
                row(OTHER, { order: 0, compare_label: CompareLabelType.Previous, breakdown_other_values_count: 9 }),
            ],
            expected:
                'Showing the 2 breakdown values with the most events across all series. 7 more are grouped in Other.',
        },
        {
            name: 'leaves out Other when every value has a row',
            results: [row('home')],
            expected: 'Showing the 1 breakdown value with the most events across all series.',
        },
        {
            name: 'keeps the plain limit when the query did not rank by event count',
            results: [row('home', { breakdown_event_count: undefined })],
            expected: 'Breakdown limited to 25 - more available',
        },
    ])('$name', ({ results, expected }) => {
        expect(getBreakdownLimitNotice(results, 25)).toEqual(expected)
    })
})
