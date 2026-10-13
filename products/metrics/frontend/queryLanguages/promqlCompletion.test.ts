import {
    type PromQLCompletionSource,
    type PromQLSituation,
    getPromQLCompletions,
    getSituation,
} from './promqlCompletion'

// `|` marks the cursor.
const at = (query: string): [string, number] => [query.replace('|', ''), query.indexOf('|')]

const source = (): PromQLCompletionSource & { calls: string[] } => {
    const calls: string[] = []
    return {
        calls,
        metricNames: async (search) => {
            calls.push(`names:${search}`)
            return [
                { name: 'http_requests_total', type: 'sum' },
                { name: 'http.server.duration', type: 'histogram' },
            ]
        },
        labelNames: async (metricName, search) => {
            calls.push(`labels:${metricName ?? ''}:${search}`)
            return ['service_name', 'http.route', 'job']
        },
        labelValues: async (labelName, metricName, search) => {
            calls.push(`values:${labelName}:${metricName ?? ''}:${search}`)
            return ['api', 'a.b "c"']
        },
        metricNamesSearchedOnServer: () => false,
    }
}

describe('PromQL autocomplete', () => {
    it.each<[string, PromQLSituation | null]>([
        ['|', { type: 'EMPTY' }],
        ['http_re|', { type: 'AT_ROOT' }],
        ['sum(|', { type: 'IN_FUNCTION' }],
        ['sum(rate(htt|', { type: 'IN_FUNCTION' }],
        ['topk(5, |', { type: 'IN_FUNCTION' }],
        ['sum(x) / |', { type: 'AT_ROOT' }],
        ['x or |', { type: 'AT_ROOT' }],
        ['rate(x[|', { type: 'IN_DURATION' }],
        ['rate(x[5m:|', { type: 'IN_DURATION' }],
        ['rate(x[5m] |', null],
        ['sum(x) |', null],
        ['x{|', { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME', metricName: 'x', otherLabels: [] }],
        ['x{jo|', { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME', metricName: 'x', otherLabels: [] }],
        [
            'x{job="api", |',
            {
                type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME',
                metricName: 'x',
                otherLabels: [{ label: 'job', op: '=', value: 'api' }],
            },
        ],
        [
            '{"http.server.duration", |',
            { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME', metricName: 'http.server.duration', otherLabels: [] },
        ],
        ['{__name__="x", |', { type: 'IN_LABEL_SELECTOR_NO_LABEL_NAME', metricName: 'x', otherLabels: [] }],
        [
            'x{job=|',
            {
                type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME',
                metricName: 'x',
                labelName: 'job',
                op: '=',
                betweenQuotes: false,
                otherLabels: [],
            },
        ],
        [
            'x{a="1", job=~"ap|',
            {
                type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME',
                metricName: 'x',
                labelName: 'job',
                op: '=~',
                betweenQuotes: true,
                otherLabels: [{ label: 'a', op: '=', value: '1' }],
            },
        ],
        [
            '{"http.server.duration", "http.route"!="|',
            {
                type: 'IN_LABEL_SELECTOR_WITH_LABEL_NAME',
                metricName: 'http.server.duration',
                labelName: 'http.route',
                op: '!=',
                betweenQuotes: true,
                otherLabels: [],
            },
        ],
        ['x{job="api"|', null],
        ['{"http.ser|', { type: 'IN_QUOTED_METRIC_NAME' }],
        ['{__name__="htt|', { type: 'IN_QUOTED_METRIC_NAME' }],
        ['sum by (|', { type: 'IN_GROUPING', metricName: undefined, usedLabels: [] }],
        ['sum by (|) (rate(errors_total))', { type: 'IN_GROUPING', metricName: 'errors_total', usedLabels: [] }],
        [
            'sum(rate(errors_total{job="a"})) by (job, |',
            { type: 'IN_GROUPING', metricName: 'errors_total', usedLabels: ['job'] },
        ],
        [
            'sum by (le) (rate({"http.server.duration_bucket"})) / on(|',
            { type: 'IN_GROUPING', metricName: 'http.server.duration_bucket', usedLabels: [] },
        ],
    ])('reads %j', (query, expected) => {
        const [text, offset] = at(query)
        expect(getSituation(text, offset)?.situation ?? null).toEqual(expected)
    })

    it('suggests metrics, aggregations and functions at the start, quoting dotted names', async () => {
        const [text, offset] = at('sum(htt|')
        const result = await getPromQLCompletions(text, offset, source())
        expect(result?.from).toBe(4)
        const byLabel = Object.fromEntries(result!.items.map((item) => [item.label, item]))
        expect(byLabel['http_requests_total']).toMatchObject({ insertText: 'http_requests_total', kind: 'metric' })
        expect(byLabel['http.server.duration']).toMatchObject({ insertText: '{"http.server.duration"}' })
        expect(byLabel['http.server.duration_bucket']).toMatchObject({ insertText: '{"http.server.duration_bucket"}' })
        expect(byLabel['rate']).toMatchObject({ insertText: 'rate($0)', snippet: true, kind: 'function' })
        expect(byLabel['quantile']).toMatchObject({ kind: 'aggregation' })
        // Names loaded once are filtered locally, so Monaco need not ask again on each keystroke.
        expect(result?.incomplete).toBe(false)
    })

    it('suggests unused label names for the selector metric, ready for a value', async () => {
        const fake = source()
        const [text, offset] = at('x{job="a", ht|}')
        const result = await getPromQLCompletions(text, offset, fake)
        expect(fake.calls).toEqual(['labels:x:ht'])
        expect(result?.items.map((item) => item.insertText)).toEqual(['service_name=', '"http.route"='])
        expect(result?.items.every((item) => item.retrigger)).toBe(true)
        expect(result?.incomplete).toBe(true)
    })

    it.each([
        ['x{job=|}', ['"api"', '"a.b \\"c\\""']],
        ['x{job="|"}', ['api', 'a.b \\"c\\"']],
        ['x{job=~"|"}', ['api', 'a\\\\.b \\"c\\"']],
    ])('quotes and escapes label values in %j', async (query, expected) => {
        const [text, offset] = at(query)
        const result = await getPromQLCompletions(text, offset, source())
        expect(result?.items.map((item) => item.insertText)).toEqual(expected)
    })

    it('suggests durations in a range and grouping labels without "="', async () => {
        const [rangeText, rangeOffset] = at('rate(x[|')
        const range = await getPromQLCompletions(rangeText, rangeOffset, source())
        expect(range?.items.map((item) => item.label)).toContain('5m')

        const [groupText, groupOffset] = at('sum by (job, |) (x)')
        const grouping = await getPromQLCompletions(groupText, groupOffset, source())
        expect(grouping?.items.map((item) => item.insertText)).toEqual(['service_name', '"http.route"'])
    })

    it('gives no suggestions when the source fails', async () => {
        const failing: PromQLCompletionSource = {
            metricNames: () => Promise.reject(new Error('down')),
            labelNames: () => Promise.reject(new Error('down')),
            labelValues: () => Promise.reject(new Error('down')),
        }
        const [text, offset] = at('x{|')
        expect((await getPromQLCompletions(text, offset, failing))?.items).toEqual([])
    })
})
