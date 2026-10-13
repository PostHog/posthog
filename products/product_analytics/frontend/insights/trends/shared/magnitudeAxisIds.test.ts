import { DEFAULT_Y_AXIS_ID } from '@posthog/quill-charts'

import { computeMagnitudeAxisIds } from './magnitudeAxisIds'

describe('computeMagnitudeAxisIds', () => {
    it.each<{ name: string; datasets: number[][]; expected: string[] }>([
        {
            name: 'similar magnitudes share the default axis',
            datasets: [
                [1, 2, 3],
                [4, 5, 6],
                [2, 8, 9],
            ],
            expected: [DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID],
        },
        {
            name: 'an order-of-magnitude gap splits into two axes, interleaved series regroup',
            datasets: [
                [1, 2, 3],
                [1000, 2000, 3000],
                [2, 4, 6],
                [5000, 1000, 2000],
            ],
            expected: [DEFAULT_Y_AXIS_ID, 'y1', DEFAULT_Y_AXIS_ID, 'y1'],
        },
        {
            name: 'the first series keeps the default axis even when its group is the largest magnitude',
            datasets: [
                [1000, 2000],
                [1, 2],
            ],
            expected: [DEFAULT_Y_AXIS_ID, 'y1'],
        },
        {
            name: 'a smooth magnitude ramp with sub-order gaps stays on one axis',
            datasets: [[5], [20], [90], [400]],
            expected: [DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID],
        },
        {
            name: 'axes are capped at four even with more magnitude clusters',
            datasets: [[1], [100], [10000], [1000000], [100000000]],
            expected: [DEFAULT_Y_AXIS_ID, 'y1', 'y2', 'y3', 'y3'],
        },
        {
            name: 'all-zero and empty series join the lowest-magnitude group',
            datasets: [[1000, 2000], [1, 2], [0, 0], []],
            expected: [DEFAULT_Y_AXIS_ID, 'y1', 'y1', 'y1'],
        },
        {
            name: 'negative values group by absolute magnitude',
            datasets: [
                [-1000, -2000],
                [900, 1100],
            ],
            expected: [DEFAULT_Y_AXIS_ID, DEFAULT_Y_AXIS_ID],
        },
        { name: 'empty input', datasets: [], expected: [] },
    ])('$name', ({ datasets, expected }) => {
        expect(computeMagnitudeAxisIds(datasets)).toEqual(expected)
    })
})
