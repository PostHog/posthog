import { type SeriesLabel, distinctSeriesLabels, formatSeriesNames } from './metricsSeries'

describe('metricsSeries', () => {
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

    describe('formatSeriesNames', () => {
        it.each<{ name: string; clauses: (string | null)[]; metricName?: string; names: string[] }>([
            {
                name: 'names unlabelled series by their clause',
                clauses: ['Requests', 'Errors'],
                names: ['Requests', 'Errors'],
            },
            {
                name: 'keeps the metric name after the clause',
                clauses: ['a', 'b'],
                metricName: 'http.requests',
                names: ['a · http.requests', 'b · http.requests'],
            },
            {
                name: 'uses the fallback for a single clause',
                clauses: ['Requests'],
                names: ['sum(rate(requests_total))'],
            },
        ])('$name', ({ clauses, metricName, names }) => {
            const series = clauses.map((clause) => ({ labels: {}, metric_name: metricName, clause }))
            expect(formatSeriesNames(series, 'sum(rate(requests_total))')).toEqual(names)
        })
    })
})
