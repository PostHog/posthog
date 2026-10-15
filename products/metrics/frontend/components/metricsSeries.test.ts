import { type SeriesLabel, distinctSeriesLabels, seriesLabelText } from './metricsSeries'

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

describe('seriesLabelText', () => {
    const labels = { 'service.name': 'api', 'host.name': 'web-2' }

    it.each<{ name: string; labels: Record<string, string>; legendFormat?: string; text: string }>([
        { name: 'joins key=value pairs by default', labels, text: 'service.name=api, host.name=web-2' },
        {
            name: 'fills each {{label}} in the legend format',
            labels,
            legendFormat: '{{service.name}} · {{host.name}}',
            text: 'api · web-2',
        },
        { name: 'allows spaces inside the braces', labels, legendFormat: '{{ host.name }}', text: 'web-2' },
        { name: 'leaves a label the series lacks empty', labels, legendFormat: '{{host.name}}{{pod}}', text: 'web-2' },
        {
            name: 'is empty for an unlabelled series, so callers fall back',
            labels: {},
            legendFormat: '{{host.name}}',
            text: '',
        },
    ])('$name', ({ labels, legendFormat, text }) => {
        expect(seriesLabelText(labels, legendFormat)).toEqual(text)
    })
})
