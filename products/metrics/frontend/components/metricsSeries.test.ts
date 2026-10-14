import { type SeriesLabel, splitSharedSeriesLabels } from './metricsSeries'

describe('splitSharedSeriesLabels', () => {
    // Regression guard: hoisting a label that differs between series makes two rows look identical.
    it.each<{ name: string; labels: Record<string, string>[]; shared: SeriesLabel[]; distinct: SeriesLabel[][] }>([
        {
            name: 'hoists labels with the same value on every series',
            labels: [
                { app: 'checkout', route: '/cart' },
                { app: 'checkout', route: '/pay' },
            ],
            shared: [['app', 'checkout']],
            distinct: [[['route', '/cart']], [['route', '/pay']]],
        },
        {
            name: 'keeps a label that one series does not have',
            labels: [{ app: 'checkout', route: '/cart' }, { route: '/pay' }],
            shared: [],
            distinct: [
                [
                    ['app', 'checkout'],
                    ['route', '/cart'],
                ],
                [['route', '/pay']],
            ],
        },
        {
            name: 'shares every label of a single series',
            labels: [{ app: 'checkout' }],
            shared: [['app', 'checkout']],
            distinct: [[]],
        },
    ])('$name', ({ labels, shared, distinct }) => {
        expect(splitSharedSeriesLabels(labels.map((seriesLabels) => ({ labels: seriesLabels })))).toEqual({
            shared,
            distinct,
        })
    })
})
