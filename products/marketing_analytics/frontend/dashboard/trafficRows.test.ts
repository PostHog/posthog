import { CompareLabelType, TrendResult } from '~/types'

import { trafficRows } from './trafficRows'

it('keeps period-wide distinct totals and aligns shuffled metrics and comparisons by channel', () => {
    const result = (breakdown: string, order: number, value: number, previous = false): TrendResult => ({
        action: null,
        order,
        breakdown_value: breakdown,
        aggregated_value: value,
        count: 999,
        data: [20, 20, 20],
        days: [],
        labels: [],
        label: breakdown,
        compare_label: previous ? CompareLabelType.Previous : CompareLabelType.Current,
    })
    expect(
        trafficRows([
            result('Organic Search', 1, 12),
            result('Direct', 0, 4, true),
            result('Organic Search', 0, 10),
            result('Direct', 0, 5),
            result('Organic Search', 0, 8, true),
            result('Organic Search', 2, 0),
        ])
    ).toEqual([
        { name: 'Organic Search', current: { 0: 10, 1: 12, 2: 0 }, previous: { 0: 8 } },
        { name: 'Direct', current: { 0: 5 }, previous: { 0: 4 } },
    ])
})
