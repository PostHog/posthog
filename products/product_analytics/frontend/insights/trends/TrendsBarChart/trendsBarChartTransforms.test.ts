import { hexToRGBA } from 'lib/utils/colors'

import type { CurrencyCode, GoalLine as SchemaGoalLine, TrendsFilter } from '~/queries/schema/schema-general'

import {
    buildTrendsBarAggregatedSeries,
    buildTrendsBarChartModel,
    buildTrendsBarTimeSeries,
    buildTrendsBarTimeSeriesConfig,
    type TrendsBarResultLike,
} from './trendsBarChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

describe('buildTrendsBarTimeSeries', () => {
    it('returns one series per result with the result data unchanged', () => {
        const results = [makeResult({ id: 'a', data: [1, 2, 3] }), makeResult({ id: 'b', data: [4, 5, 6] })]
        const series = buildTrendsBarTimeSeries(results, { getColor: () => RED })

        expect(series).toHaveLength(2)
        expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        expect(series[0].data).toEqual([1, 2, 3])
        expect(series[1].data).toEqual([4, 5, 6])
    })

    it.each([
        { compare_label: undefined, expectedColor: RED },
        { compare_label: 'previous' as const, expectedColor: hexToRGBA(RED, 0.5) },
    ])(
        'applies getColor and dims compare-previous to 0.5 alpha (compare_label=$compare_label)',
        ({ compare_label, expectedColor }) => {
            const series = buildTrendsBarTimeSeries([makeResult({ compare_label })], { getColor: () => RED })
            expect(series[0].color).toBe(expectedColor)
        }
    )

    // The shared dimHexColor must match lib/utils' hexToRGBA for valid hex (incl. 3-digit shorthand);
    // a non-hex color is passed through unchanged (the one intentional divergence from hexToRGBA).
    it.each([
        { base: '#ff0000', expected: hexToRGBA('#ff0000', 0.5) },
        { base: '#f00', expected: hexToRGBA('#f00', 0.5) },
        { base: 'not-a-hex', expected: 'not-a-hex' },
    ])('dims a compare-previous bar for $base', ({ base, expected }) => {
        const series = buildTrendsBarTimeSeries([makeResult({ compare_label: 'previous' })], { getColor: () => base })
        expect(series[0].color).toBe(expected)
    })

    it('marks a series excluded when getHidden returns true', () => {
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            getHidden: () => true,
        })
        expect(series[0].visibility).toEqual({ excluded: true })
    })

    it('attaches the meta payload returned by buildMeta', () => {
        const meta = { breakdown_value: 'spike', order: 7 }
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            buildMeta: () => meta,
        })
        expect(series[0].meta).toBe(meta)
    })

    it('falls back to empty string label when result label is null', () => {
        const series = buildTrendsBarTimeSeries([makeResult({ label: null })], { getColor: () => RED })
        expect(series[0].label).toBe('')
    })

    it.each([
        { showMultipleYAxes: undefined, expected: ['left', 'left', 'left'] },
        { showMultipleYAxes: true, expected: ['left', 'y1', 'y2'] },
    ])('assigns yAxisId per series (showMultipleYAxes=$showMultipleYAxes)', ({ showMultipleYAxes, expected }) => {
        const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' }), makeResult({ id: 'c' })]
        const series = buildTrendsBarTimeSeries(results, { getColor: () => RED, showMultipleYAxes })
        expect(series.map((s) => s.yAxisId)).toEqual(expected)
    })
})

describe('buildTrendsBarAggregatedSeries', () => {
    const mkResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
        id: 0,
        label: 'Pageview',
        data: [],
        aggregated_value: 42,
        ...overrides,
    })

    it('returns display labels aligned with results, in the same order; band labels stay unique', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 1 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 2 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 3 }),
        ]
        const { labels, displayLabels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(displayLabels).toEqual(['A', 'B', 'C'])
        expect(new Set(labels).size).toBe(labels.length)
    })

    it('splits same-label results into separate bands when they come from different series (no breakdown)', () => {
        // Four trends series of the same event surface label="$pageview" each but have
        // distinct action.order — they should not collapse onto one band.
        const results = [0, 1, 2, 3].map((order) =>
            mkResult({ id: `r${order}`, label: '$pageview', action: { order } })
        )
        const { labels, displayLabels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(displayLabels).toEqual(['$pageview', '$pageview', '$pageview', '$pageview'])
        expect(new Set(labels).size).toBe(4)
    })

    // Formula+breakdown shape: each formula carries a top-level `order`; breakdown rows of the
    // same formula share both the formula label and the order. They must NOT collapse by default.
    const formulaBreakdownSpec: [string, number][] = [
        ['Binary Size', 0],
        ['Binary Size', 0],
        ['Binary Size', 0],
        ['Embedded Assets', 1],
        ['Embedded Assets', 1],
        ['Runtime & Code', 2],
        ['Runtime & Code', 2],
    ]

    it.each([
        { name: 'separate by default — one band per breakdown value', stackBreakdowns: undefined, expectedBands: 7 },
        { name: 'one band per formula when stackBreakdowns is set', stackBreakdowns: true, expectedBands: 3 },
    ])('formula breakdown rows: $name', ({ stackBreakdowns, expectedBands }) => {
        const results = formulaBreakdownSpec.map(([label, order], i) => mkResult({ id: `r${i}`, label, order }))
        const { labels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED, stackBreakdowns })
        expect(new Set(labels).size).toBe(expectedBands)
    })

    it('keeps each result label as its band display label in separate mode', () => {
        const results = formulaBreakdownSpec.map(([label, order], i) => mkResult({ id: `r${i}`, label, order }))
        const { displayLabels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(displayLabels).toEqual(formulaBreakdownSpec.map(([label]) => label))
    })

    it('keeps current and previous on separate bands in stacked mode even at the same order', () => {
        const results = [
            mkResult({ id: 'a', label: 'F', order: 0, compare_label: 'current', breakdown_value: 'Chrome' }),
            mkResult({ id: 'b', label: 'F', order: 0, compare_label: 'current', breakdown_value: 'Safari' }),
            mkResult({ id: 'c', label: 'F', order: 0, compare_label: 'previous', breakdown_value: 'Chrome' }),
        ]
        const { labels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED, stackBreakdowns: true })
        expect(new Set(labels).size).toBe(2)
    })

    it('uses getDisplayLabel for the category label when provided', () => {
        const results = [mkResult({ id: 'a', label: 'Formula (A + B)', breakdown_value: 'Chrome' })]
        const { displayLabels } = buildTrendsBarAggregatedSeries(results, {
            getColor: () => RED,
            getDisplayLabel: (r) => String(r.breakdown_value),
        })
        expect(displayLabels).toEqual(['Chrome'])
    })

    it('collapses to a single series whose data holds each band value in order', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 10 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 20 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 30 }),
        ]
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(series).toHaveLength(1)
        expect(series[0].data).toEqual([10, 20, 30])
    })

    it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, undefined])(
        'replaces non-finite aggregated_value (%p) with 0',
        (badValue) => {
            const { series } = buildTrendsBarAggregatedSeries([mkResult({ aggregated_value: badValue })], {
                getColor: () => RED,
            })
            expect(series[0].data).toEqual([0])
        }
    )

    it('exposes per-result colors and labels as per-bar entries on the single series', () => {
        const colors = ['#aaa', '#bbb', '#ccc']
        const results = colors.map((_, i) => mkResult({ id: `r${i}`, label: `L${i}` }))
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: (_r, i) => colors[i] })
        expect(series).toHaveLength(1)
        expect(series[0].bars?.map((b) => b.color)).toEqual(colors)
        expect(series[0].bars?.map((b) => b.label)).toEqual(['L0', 'L1', 'L2'])
        // Series-level color falls back to the first bar so a tooltip/legend has something sane.
        expect(series[0].color).toBe(colors[0])
    })

    it('dims the previous-compare bar color, matching the time-series builder', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', compare_label: 'current' }),
            mkResult({ id: 'b', label: 'B', compare_label: 'previous' }),
        ]
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(series[0].bars?.map((b) => b.color)).toEqual([RED, hexToRGBA(RED, 0.5)])
    })

    it('builds per-bar meta by index when buildMeta is provided', () => {
        const results = [mkResult({ id: 'a' }), mkResult({ id: 'b' })]
        const { series } = buildTrendsBarAggregatedSeries<TrendsBarResultLike, { idx: number }>(results, {
            getColor: () => RED,
            buildMeta: (_r, i) => ({ idx: i }),
        })
        expect(series[0].bars?.map((b) => b.meta)).toEqual([{ idx: 0 }, { idx: 1 }])
    })

    it('keeps the sparse multi-series stack when stackBreakdowns is set', () => {
        const results = [
            mkResult({ id: 'a', label: 'F', order: 0, breakdown_value: 'Chrome', aggregated_value: 10 }),
            mkResult({ id: 'b', label: 'F', order: 0, breakdown_value: 'Safari', aggregated_value: 20 }),
        ]
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED, stackBreakdowns: true })
        // Stacked breakdowns share a band and genuinely stack, so they stay as one series per row.
        expect(series).toHaveLength(2)
        expect(series[0].data).toEqual([10, 0])
        expect(series[1].data).toEqual([0, 20])
    })

    it.each([
        {
            name: 'suffixes display labels with compare_label so compare-against-previous rows render distinctly',
            results: [
                { id: 'a', label: 'Microsoft Edge', compare_label: 'current', aggregated_value: 100 },
                { id: 'b', label: 'Microsoft Edge', compare_label: 'previous', aggregated_value: 80 },
                { id: 'c', label: 'Safari', compare_label: 'current', aggregated_value: 60 },
            ] satisfies Partial<TrendsBarResultLike>[],
            expected: ['Microsoft Edge - current', 'Microsoft Edge - previous', 'Safari - current'],
        },
        {
            name: 'leaves display labels unchanged when compare_label is absent',
            results: [
                { id: 'a', label: 'Chrome', aggregated_value: 1 },
                { id: 'b', label: 'Safari', aggregated_value: 2 },
            ] satisfies Partial<TrendsBarResultLike>[],
            expected: ['Chrome', 'Safari'],
        },
    ])('$name', ({ results, expected }) => {
        const { labels, displayLabels } = buildTrendsBarAggregatedSeries(results.map(mkResult), {
            getColor: () => RED,
        })
        expect(displayLabels).toEqual(expected)
        // Distinct display labels → distinct band keys after the series-id suffix.
        expect(new Set(labels).size).toBe(labels.length)
    })

    it('drops hidden results so visible bars are densely packed', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 1 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 2 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 3 }),
        ]
        const { series, displayLabels } = buildTrendsBarAggregatedSeries(results, {
            getColor: () => RED,
            getHidden: (_r, i) => i === 1,
        })
        expect(displayLabels).toEqual(['A', 'C'])
        expect(series).toHaveLength(1)
        expect(series[0].data).toEqual([1, 3])
    })
})

describe('buildTrendsBarTimeSeriesConfig', () => {
    it.each([
        { isPercentStackView: false, isGrouped: false, expected: 'stacked', expectedDiverging: true },
        { isPercentStackView: false, isGrouped: true, expected: 'grouped', expectedDiverging: false },
        { isPercentStackView: true, isGrouped: false, expected: 'percent', expectedDiverging: false },
        { isPercentStackView: true, isGrouped: true, expected: 'percent', expectedDiverging: false },
    ])(
        'maps isPercentStackView=$isPercentStackView / isGrouped=$isGrouped to barLayout=$expected / divergingStack=$expectedDiverging',
        ({ isPercentStackView, isGrouped, expected, expectedDiverging }) => {
            const cfg = buildTrendsBarTimeSeriesConfig({ isPercentStackView, isGrouped })
            expect(cfg.barLayout).toBe(expected)
            expect(cfg.divergingStack).toBe(expectedDiverging)
        }
    )

    it.each([
        {
            name: 'builds the xAxis from interval/timezone/allDays',
            input: { interval: 'day' as const, timezone: 'UTC', allDays: ['2024-06-10', '2024-06-11'] },
            expected: {
                label: undefined,
                timezone: 'UTC',
                interval: 'day',
                allDays: ['2024-06-10', '2024-06-11'],
            },
        },
        {
            name: 'defaults interval to "day" and allDays to empty when omitted',
            input: {},
            expected: { label: undefined, timezone: undefined, interval: 'day', allDays: [] },
        },
    ])('$name', ({ input, expected }) => {
        const cfg = buildTrendsBarTimeSeriesConfig({ isPercentStackView: false, isGrouped: false, ...input })
        expect(cfg.xAxis).toEqual(expected)
    })

    it('forwards the y-axis from buildTrendsYAxisConfig with showGrid: true', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'duration', aggregationAxisPrefix: '~' }
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            trendsFilter,
            baseCurrency: 'USD' as CurrencyCode,
            yAxisScaleType: 'log10',
        })
        expect(cfg.yAxis).toMatchObject({
            format: 'duration',
            prefix: '~',
            currency: 'USD',
            scale: 'log',
            showGrid: true,
        })
    })

    it('forces percentage_scaled format when isPercentStackView is true', () => {
        // BarChart percent layout puts the value scale on 0..1, so the y-tick formatter
        // expects 0..1 input rather than the 0..100 input of the regular `percentage` format.
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: true,
            isGrouped: false,
            trendsFilter: { aggregationAxisFormat: 'currency' },
        })
        expect(cfg.yAxis?.format).toBe('percentage_scaled')
    })

    it('maps schema goal lines through the shared adapter', () => {
        const goalLines: SchemaGoalLine[] = [{ value: 50, label: 'Target' }]
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            goalLines,
        })
        expect(cfg.goalLines).toEqual([expect.objectContaining({ value: 50, label: 'Target' })])
    })

    it('passes custom axis labels into the chart config', () => {
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            xAxisLabel: 'Signup date',
            yAxisLabel: 'Total events',
        })
        expect(cfg.xAxis?.label).toBe('Signup date')
        expect(cfg.yAxis?.label).toBe('Total events')
    })

    it('passes valueLabels and tooltip through unchanged', () => {
        const formatter = (v: number): string => `~${v}`
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            valueLabels: { formatter },
            tooltip: { pinnable: true, placement: 'top' },
        })
        expect(cfg.valueLabels).toEqual({ formatter })
        expect(cfg.tooltip).toEqual({ pinnable: true, placement: 'top' })
    })
})

describe('buildTrendsBarChartModel', () => {
    const results: TrendsBarResultLike[] = [
        { id: 'a', label: 'Pageview', data: [1, 2, 3] },
        { id: 'b', label: 'Signup', data: [4, 5, 6] },
    ]

    it('assembles series + config and passes the host labels through', () => {
        const model = buildTrendsBarChartModel(results, {
            getColor: () => RED,
            labels: ['Mon', 'Tue', 'Wed'],
            isPercentStackView: false,
            isGrouped: false,
        })

        expect(model.labels).toEqual(['Mon', 'Tue', 'Wed'])
        expect(model.series.map((s) => s.key)).toEqual(['a', 'b'])
        expect(model.series[0].data).toEqual([1, 2, 3])
        expect(model.series[0].color).toBe(RED)
        expect(model.config.barLayout).toBe('stacked')
    })

    it.each([
        { isGrouped: false, isPercentStackView: false, expected: 'stacked' },
        { isGrouped: true, isPercentStackView: false, expected: 'grouped' },
        { isGrouped: false, isPercentStackView: true, expected: 'percent' },
        { isGrouped: true, isPercentStackView: true, expected: 'percent' },
    ])('maps layout flags to barLayout=$expected', ({ isGrouped, isPercentStackView, expected }) => {
        const model = buildTrendsBarChartModel(results, {
            getColor: () => RED,
            labels: [],
            isGrouped,
            isPercentStackView,
        })
        expect(model.config.barLayout).toBe(expected)
    })

    it('forwards an x-axis tick formatter into the config', () => {
        const model = buildTrendsBarChartModel(results, {
            getColor: () => RED,
            labels: [],
            isPercentStackView: false,
            isGrouped: false,
            xAxisTickFormatter: (value) => `~${value}`,
        })
        const { tickFormatter } = model.config.xAxis!
        expect(tickFormatter).toBeTruthy()
        expect(tickFormatter!('2024-01-01', 0)).toBe('~2024-01-01')
    })
})
