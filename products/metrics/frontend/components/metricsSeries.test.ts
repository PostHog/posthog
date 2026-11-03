import { type SeriesLabel, distinctSeriesLabels } from './metricsSeries'

describe('distinctSeriesLabels', () => {
    it.each<{ name: string; labels: Record<string, string>[]; distinct: SeriesLabel[][] }>([
        {
            name: 'drops labels with the same value on every series',
            labels: [
                { app: 'checkout', route: '/cart' },
                { app: 'checkout', route: '/pay' },
            ],
            distinct: [[['route', '/cart']], [['route', '/pay']]],
        },
        {
            name: 'keeps a label that one series does not have',
            labels: [{ app: 'checkout', route: '/cart' }, { route: '/pay' }],
            distinct: [
                [
                    ['app', 'checkout'],
                    ['route', '/cart'],
                ],
                [['route', '/pay']],
            ],
        },
        {
            name: 'keeps every label of a single series',
            labels: [{ app: 'checkout' }],
            distinct: [[['app', 'checkout']]],
        },
    ])('$name', ({ labels, distinct }) => {
        expect(distinctSeriesLabels(labels.map((seriesLabels) => ({ labels: seriesLabels })))).toEqual(distinct)
    })
})
