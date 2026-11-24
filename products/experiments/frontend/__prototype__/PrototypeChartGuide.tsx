/**
 * Scratch prototype v17: a documentation page that compares every prototype result chart with today's
 * violin, bar and time series charts. Today's charts are the product components, fed the same fake results.
 * Not committed.
 */
import '~/scenes/experiments/MetricsView/new/MetricRowGroup.scss'

import { useId, useMemo } from 'react'

import {
    Badge,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Heading,
    Separator,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Text,
} from '@posthog/quill'

import { useChartTheme } from 'lib/charts/hooks'

import {
    type ExperimentMetric,
    ExperimentMetricType,
    type ExperimentVariantResultBayesian,
    type ExperimentVariantResultFrequentist,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ChartCell } from '~/scenes/experiments/MetricsView/new/ChartCell'
import { SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from '~/scenes/experiments/MetricsView/new/constants'
import { useAxisScale } from '~/scenes/experiments/MetricsView/new/useAxisScale'
import { VariantTimeseriesChart } from '~/scenes/experiments/MetricsView/new/VariantTimeseriesChart'
import { COLORS } from '~/scenes/experiments/MetricsView/shared/colors'
import { type ExperimentVariantResult, getNiceTickValues } from '~/scenes/experiments/MetricsView/shared/utils'

import {
    EXPOSURES,
    PRIMARY_METRICS,
    type PrototypeMetric,
    type PrototypeVariantResult,
    VARIANTS,
} from './prototypeData'
import { AllMetricsTrendChart, CandlestickChart, MetricMatrix, isSignificant } from './PrototypeMetricViews'
import { AllMetricsCandlestick, MetricRowMatrix } from './PrototypeMetricViewsV16'
import { metricTrends } from './prototypeTimeseries'
import { PrototypeTrendChart } from './PrototypeTrendChart'

const CHECKOUT = PRIMARY_METRICS[0]
const ITEMS = PRIMARY_METRICS[2]
const ROW_PX = 51

/** A metric the product charts can read. Only `goal` changes how they draw. */
function productMetric(goal: 'increase' | 'decrease' = 'increase'): ExperimentMetric {
    return {
        kind: NodeKind.ExperimentMetric,
        uuid: `guide-${goal}`,
        metric_type: ExperimentMetricType.FUNNEL,
        series: [],
        goal,
    } as unknown as ExperimentMetric
}

function bayesian(variant: PrototypeVariantResult): ExperimentVariantResultBayesian {
    return {
        method: 'bayesian',
        key: variant.key,
        number_of_samples: 4150,
        sum: 0,
        sum_squares: 0,
        credible_interval: variant.interval ?? undefined,
        chance_to_win: variant.chanceToWin ?? undefined,
        significant: isSignificant(variant),
    }
}

function frequentist(variant: PrototypeVariantResult): ExperimentVariantResultFrequentist {
    return {
        method: 'frequentist',
        key: variant.key,
        number_of_samples: 4150,
        sum: 0,
        sum_squares: 0,
        confidence_interval: variant.interval ?? undefined,
        significant: isSignificant(variant),
        p_value: isSignificant(variant) ? 0.01 : 0.2,
    }
}

/** Today's table axis: symmetric, the largest interval end plus a margin, for every metric in the table. */
function productAxisRange(metrics: PrototypeMetric[]): number {
    const max = Math.max(
        ...metrics.flatMap((metric) => metric.variants.flatMap((variant) => (variant.interval ?? []).map(Math.abs)))
    )
    return Math.min(max + Math.max(max * 0.05, 0.1), 1.5)
}

function percent(value: number, digits = 1): string {
    return `${value > 0 ? '+' : ''}${(value * 100).toFixed(digits)}%`
}

function useVariantColors(): Record<string, string> {
    const theme = useChartTheme()
    return useMemo(
        () => Object.fromEntries(VARIANTS.map((key, index) => [key, theme.colors[index % theme.colors.length]])),
        [theme]
    )
}

/** The tick labels today's table puts under its chart column, on the same scale as `ChartCell`. */
function ProductTicks({ axisRange }: { axisRange: number }): JSX.Element {
    const scale = useAxisScale(axisRange, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
    return (
        <div className="relative h-5">
            {getNiceTickValues(axisRange).map((tick) => (
                <span
                    key={tick}
                    className="absolute -translate-x-1/2 text-[10px] tabular-nums text-muted-foreground"
                    style={{ left: `${(scale(tick) / VIEW_BOX_WIDTH) * 100}%` }}
                >
                    {percent(tick, 0)}
                </span>
            ))}
        </div>
    )
}

/** Today's chart column for one or more metrics: one `ChartCell` per variant, as the results table draws it. */
function ProductIntervals({
    metrics,
    method,
    goal = 'increase',
    axisRange,
}: {
    metrics: PrototypeMetric[]
    method: 'bayesian' | 'frequentist'
    goal?: 'increase' | 'decrease'
    axisRange: number
}): JSX.Element {
    const metric = productMetric(goal)
    /** ChartCell names its SVG gradients from these ids, and the first definition of an id wins page wide. */
    const blockId = useId()
    return (
        <div className="flex flex-col">
            <table className="w-full border-collapse">
                <tbody>
                    {metrics.flatMap((item, metricIndex) =>
                        item.variants.map((variant, variantIndex) => {
                            const result: ExperimentVariantResult =
                                method === 'bayesian' ? bayesian(variant) : frequentist(variant)
                            return (
                                <tr key={`${item.name}-${variant.key}`} style={{ height: ROW_PX }}>
                                    <td className="w-28 whitespace-nowrap pr-2 align-middle">
                                        {variantIndex === 0 && metrics.length > 1 ? (
                                            <Text size="xxs" variant="muted" render={<span className="block" />}>
                                                {`${metricIndex + 1}. ${item.name}`}
                                            </Text>
                                        ) : null}
                                        <span className="font-mono text-xs">{variant.key}</span>
                                    </td>
                                    {variant.interval ? (
                                        <ChartCell
                                            variantResult={result}
                                            metric={metric}
                                            axisRange={axisRange}
                                            metricUuid={`guide-${blockId}-${metricIndex}`}
                                            gradientSuffix={`${variant.key}-${metricIndex}`}
                                        />
                                    ) : (
                                        <td className="align-middle text-center text-xs text-muted-foreground">
                                            Baseline, no bar
                                        </td>
                                    )}
                                </tr>
                            )
                        })
                    )}
                </tbody>
            </table>
            <div className="pl-28">
                <ProductTicks axisRange={axisRange} />
            </div>
        </div>
    )
}

/** Today's time series for one variant, as the details modal draws it. */
function ProductTimeseries({
    metric,
    variantKey,
    color,
}: {
    metric: PrototypeMetric
    variantKey: string
    color: string
}): JSX.Element {
    const trend = metricTrends(metric).find((item) => item.key === variantKey)
    const chartData = useMemo(
        () => ({
            labels: EXPOSURES.days,
            computedAt: null,
            variantColor: color,
            processedData: EXPOSURES.days.map((date, index) => ({
                date,
                value: trend?.delta[index] ?? null,
                lower_bound: trend?.lower[index] ?? null,
                upper_bound: trend?.upper[index] ?? null,
                hasRealData: true,
                significant: !!trend && (trend.lower[index] > 0 || trend.upper[index] < 0),
            })),
        }),
        [trend, color]
    )
    return <VariantTimeseriesChart chartData={chartData} />
}

function Notes({ items }: { items: string[] }): JSX.Element {
    return (
        <ul className="m-0 flex list-disc flex-col gap-1 pl-4">
            {items.map((item) => (
                <li key={item}>
                    <Text size="xs">{item}</Text>
                </li>
            ))}
        </ul>
    )
}

function Panel({
    source,
    title,
    notes,
    children,
}: {
    source: 'Today' | 'Prototype'
    title: string
    notes: string[]
    children: React.ReactNode
}): JSX.Element {
    return (
        <Card size="sm" className="min-w-0 gap-3">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Badge variant={source === 'Today' ? 'default' : 'info'}>{source}</Badge>
                    {title}
                </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                <div className="min-w-0">{children}</div>
                <Separator />
                <Notes items={notes} />
            </CardContent>
        </Card>
    )
}

function Section({
    title,
    description,
    children,
}: {
    title: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading size="md" render={<h2 className="m-0" />}>
                    {title}
                </Heading>
                <Text size="sm" variant="muted">
                    {description}
                </Text>
            </div>
            {children}
        </section>
    )
}

function Swatch({ color, label }: { color: string; label: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
            <span className="inline-block size-3 rounded-[3px] border border-border" style={{ background: color }} />
            <span>{label}</span>
        </span>
    )
}

function DataTable(): JSX.Element {
    return (
        <Card size="sm" flush className="overflow-clip">
            <Table size="sm" fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead>Metric</TableHead>
                        <TableHead>Variant</TableHead>
                        <TableHead align="right">Delta</TableHead>
                        <TableHead align="right">95% interval</TableHead>
                        <TableHead align="right">Interval midpoint</TableHead>
                        <TableHead align="right">Chance to win</TableHead>
                        <TableHead>Result</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {PRIMARY_METRICS.flatMap((metric, metricIndex) =>
                        metric.variants
                            .filter((variant) => variant.interval)
                            .map((variant) => (
                                <TableRow key={`${metric.name}-${variant.key}`}>
                                    <TableCell>{`${metricIndex + 1}. ${metric.name}`}</TableCell>
                                    <TableCell className="font-mono">{variant.key}</TableCell>
                                    <TableCell align="right" className="tabular-nums">
                                        {percent(variant.delta ?? 0)}
                                    </TableCell>
                                    <TableCell align="right" className="tabular-nums">
                                        {`${percent(variant.interval![0])} to ${percent(variant.interval![1])}`}
                                    </TableCell>
                                    <TableCell align="right" className="tabular-nums">
                                        {percent((variant.interval![0] + variant.interval![1]) / 2)}
                                    </TableCell>
                                    <TableCell align="right" className="tabular-nums">
                                        {`${Math.round((variant.chanceToWin ?? 0) * 100)}%`}
                                    </TableCell>
                                    <TableCell>
                                        {isSignificant(variant) ? (
                                            <Badge variant={(variant.delta ?? 0) > 0 ? 'success' : 'destructive'}>
                                                {(variant.delta ?? 0) > 0 ? 'Significant gain' : 'Significant loss'}
                                            </Badge>
                                        ) : (
                                            <Badge>Not significant</Badge>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))
                    )}
                </TableBody>
            </Table>
        </Card>
    )
}

const ENCODING_ROWS: { element: string; today: React.ReactNode; prototype: React.ReactNode }[] = [
    {
        element: 'Delta',
        today: 'A black vertical line. It is drawn at the middle of the interval, not at a separate point estimate.',
        prototype:
            'Candlestick: the line inside the box. Delta over time: the line at the last day. Matrix: the number in the cell. All use the reported delta.',
    },
    {
        element: 'Uncertainty',
        today: 'Bayesian: a violin from the lower to the upper end of the 95% credible interval, widest at the delta. Frequentist: a flat bar over the 95% confidence interval.',
        prototype:
            'Candlestick: whiskers are the 95% interval, the box is the 50% interval (computed from the 95% interval, assuming a normal shape). Delta over time: a band for the 95% interval on each day. Matrix: not shown.',
    },
    {
        element: 'Direction color',
        today: (
            <span className="flex flex-col gap-1">
                <span className="flex flex-wrap gap-3">
                    <Swatch color={COLORS.BAR_POSITIVE} label="Gain, right of 0%" />
                    <Swatch color={COLORS.BAR_NEGATIVE} label="Loss, left of 0%" />
                </span>
                <span>
                    An interval that crosses 0% is split at 0%: red on the left, green on the right. For a metric with
                    the goal "decrease", red and green swap.
                </span>
            </span>
        ),
        prototype: (
            <span className="flex flex-col gap-1">
                <span className="flex flex-wrap gap-3">
                    <Swatch color="var(--success-foreground)" label="Significant gain" />
                    <Swatch color="var(--destructive-foreground)" label="Significant loss" />
                    <Swatch color="var(--muted-foreground)" label="Not significant" />
                </span>
                <span>
                    Used only in the matrix and in the Delta column text. The quill status tokens, not today's chart
                    greens and reds. The matrix swaps them for a "decrease" goal. The Delta column text does not yet.
                </span>
            </span>
        ),
    },
    {
        element: 'Significance',
        today: (
            <span className="flex flex-col gap-1">
                <span>Bayesian: full color when significant, 50% opacity when not.</span>
                <span className="flex flex-wrap gap-3">
                    <span>Frequentist: full color when significant,</span>
                    <Swatch color={COLORS.BAR_DEFAULT} label="solid gray when not" />
                </span>
            </span>
        ),
        prototype:
            'Matrix: color or gray. Delta column: green or red bold text, or muted text. Candlestick and Delta over time: not encoded; read it from where the whiskers or band sit against 0%.',
    },
    {
        element: 'Variant identity',
        today: 'The row label. Bars carry no variant color. The time series line uses the variant color.',
        prototype: (
            <span className="flex flex-wrap gap-3">
                <span>The theme palette, in variant order:</span>
                <VariantSwatches />
            </span>
        ),
    },
    {
        element: 'Zero',
        today: <Swatch color={COLORS.ZERO_LINE} label="A darker grid line at 0%; the time series has a 0% goal line" />,
        prototype: 'Delta over time: a dashed line at 0%. Candlestick: control is a point at 0%. Matrix: none.',
    },
    {
        element: 'Axis',
        today: 'One symmetric axis for every metric in the table: the largest interval end plus a margin, capped at ±150%.',
        prototype:
            'Delta over time: one symmetric axis per section, like today. Candlestick per metric: each metric gets its own axis (BoxPlot cannot fix it). Candlestick in one chart: one axis for all metrics.',
    },
    {
        element: 'Time',
        today: 'One variant per chart, in the metric details. Days not computed yet draw as a dashed tail.',
        prototype:
            'Every variant of a metric in its row, or every metric of a section in one chart. No pending tail yet.',
    },
]

function VariantSwatches(): JSX.Element {
    const colors = useVariantColors()
    return (
        <>
            {VARIANTS.map((key) => (
                <Swatch key={key} color={colors[key]} label={key} />
            ))}
        </>
    )
}

function EncodingTable(): JSX.Element {
    return (
        <Card size="sm" flush className="overflow-clip">
            <Table size="sm" fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead className="w-36">What</TableHead>
                        <TableHead>Today (violin, bar, time series)</TableHead>
                        <TableHead>Prototype (candlestick, matrix, delta over time)</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {ENCODING_ROWS.map((row) => (
                        <TableRow key={row.element} className="align-top">
                            <TableCell className="font-medium">{row.element}</TableCell>
                            <TableCell className="whitespace-normal text-xs">{row.today}</TableCell>
                            <TableCell className="whitespace-normal text-xs">{row.prototype}</TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Card>
    )
}

/** Three results that cover the color rules: a significant gain, a significant loss, and no significant change. */
const CASES: { label: string; metric: PrototypeMetric; variantKey: string }[] = [
    { label: 'Significant gain: one-page on Checkout completed', metric: CHECKOUT, variantKey: 'one-page' },
    { label: 'Significant loss: compact-cart on Items per order', metric: ITEMS, variantKey: 'compact-cart' },
    { label: 'Not significant: compact-cart on Checkout completed', metric: CHECKOUT, variantKey: 'compact-cart' },
]

function caseMetric(metric: PrototypeMetric, variantKey: string): PrototypeMetric {
    return {
        ...metric,
        variants: metric.variants.filter((variant) => variant.key === 'control' || variant.key === variantKey),
    }
}

function CasesGrid(): JSX.Element {
    const axisRange = productAxisRange(PRIMARY_METRICS)
    return (
        <Card size="sm" flush className="overflow-x-auto">
            <table className="w-full min-w-[56rem] border-collapse text-left">
                <thead>
                    <tr className="border-b border-border">
                        <th className="w-56 p-3 text-xs font-medium text-muted-foreground">Result</th>
                        <th className="p-3 text-xs font-medium text-muted-foreground">Today, Bayesian violin</th>
                        <th className="p-3 text-xs font-medium text-muted-foreground">Today, frequentist bar</th>
                        <th className="p-3 text-xs font-medium text-muted-foreground">Prototype, candlestick</th>
                        <th className="p-3 text-xs font-medium text-muted-foreground">Prototype, matrix</th>
                    </tr>
                </thead>
                <tbody>
                    {CASES.map((item) => {
                        const metric = caseMetric(item.metric, item.variantKey)
                        const variant = metric.variants[1]
                        return (
                            <tr key={item.label} className="border-b border-border last:border-b-0">
                                <td className="p-3 align-middle">
                                    <Text size="xs" weight="medium" render={<span className="block" />}>
                                        {item.label}
                                    </Text>
                                    <Text size="xxs" variant="muted" render={<span className="block" />}>
                                        {`${percent(variant.delta ?? 0)}, ${percent(variant.interval![0])} to ${percent(variant.interval![1])}`}
                                    </Text>
                                </td>
                                <td className="p-2 align-middle">
                                    <ProductIntervals
                                        metrics={[{ ...metric, variants: [variant] }]}
                                        method="bayesian"
                                        axisRange={axisRange}
                                    />
                                </td>
                                <td className="p-2 align-middle">
                                    <ProductIntervals
                                        metrics={[{ ...metric, variants: [variant] }]}
                                        method="frequentist"
                                        axisRange={axisRange}
                                    />
                                </td>
                                <td className="p-2 align-middle">
                                    <CandlestickChart metric={metric} height={96} />
                                </td>
                                <td className="p-2 align-middle">
                                    <MetricRowMatrix metric={metric} height={96} />
                                </td>
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </Card>
    )
}

/** Invented to show the "decrease" goal rule: fewer support tickets is good, so a drop must read as a win. */
const DECREASE_EXAMPLE: PrototypeMetric = {
    name: 'Support ticket opened',
    kind: 'Funnel',
    goal: 'decrease',
    variants: [
        { key: 'control', value: '1.9%', detail: '79 / 4,155', delta: null, interval: null, chanceToWin: null },
        {
            key: 'one-page',
            value: '1.5%',
            detail: '62 / 4,144',
            delta: -0.21,
            interval: [-0.38, -0.04],
            chanceToWin: 0.98,
        },
    ],
} as PrototypeMetric

export function PrototypeChartGuide(): JSX.Element {
    const colors = useVariantColors()
    const axisRange = productAxisRange(PRIMARY_METRICS)
    const limit = 0.15
    return (
        <div data-quill className="min-h-screen bg-background text-foreground">
            <div className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-8">
                <header className="flex flex-col gap-2">
                    <Text size="xs" variant="muted">
                        Prototype v17 · documentation only
                    </Text>
                    <Heading size="xl" render={<h1 className="m-0" />}>
                        Experiment result charts: today and prototype
                    </Heading>
                    <Text size="sm" variant="muted" className="max-w-3xl">
                        Every chart on this page draws the same results: one experiment, three primary metrics, two test
                        variants against control. Today&apos;s charts are the product components (ChartCell for the
                        violin and the bar, VariantTimeseriesChart for the time series) fed the prototype&apos;s fake
                        results. Prototype charts are the v15 and v16 views.
                    </Text>
                </header>

                <Section
                    title="The results"
                    description="The numbers every chart below draws. Today's charts place the delta at the interval midpoint, so their line can sit a little away from the delta in the table."
                >
                    <DataTable />
                </Section>

                <Section
                    title="What each mark means"
                    description="The same idea encoded in each chart family. Read across a row to see how one fact moves from today's charts to the prototype."
                >
                    <EncodingTable />
                </Section>

                <Section
                    title="One result in every chart"
                    description="A significant gain, a significant loss and no significant change, drawn by each chart. All use today's table axis, except the candlestick, which sets its own."
                >
                    <CasesGrid />
                </Section>

                <Section
                    title="Latest result for one metric"
                    description="Checkout completed, both test variants. These sit in the chart column of the metric's rows."
                >
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                        <Panel
                            source="Today"
                            title="Violin (Bayesian)"
                            notes={[
                                'The violin spans the 95% credible interval and is widest at the delta line.',
                                'compact-cart crosses 0%, so it is red left of 0% and green right of it, at 50% opacity because it is not significant.',
                                'one-page is fully right of 0% and significant, so it is solid green.',
                                'Control has no bar; it is the baseline.',
                            ]}
                        >
                            <ProductIntervals metrics={[CHECKOUT]} method="bayesian" axisRange={axisRange} />
                        </Panel>
                        <Panel
                            source="Today"
                            title="Bar (frequentist)"
                            notes={[
                                'The bar spans the 95% confidence interval; it has no shape, every value in it reads the same.',
                                'Not significant is solid gray, with no red or green.',
                                'The black line is the interval midpoint.',
                            ]}
                        >
                            <ProductIntervals metrics={[CHECKOUT]} method="frequentist" axisRange={axisRange} />
                        </Panel>
                        <Panel
                            source="Prototype"
                            title="Candlestick, chart per metric"
                            notes={[
                                'Whiskers = the violin ends (95% interval). Box = the middle half of the violin (50% interval). Line = delta.',
                                'One color for all boxes; direction is read against the 0% point (control).',
                                'Own axis for this metric, so a box here is not to scale with another metric.',
                            ]}
                        >
                            <CandlestickChart metric={CHECKOUT} height={3 * 56} />
                        </Panel>
                        <Panel
                            source="Prototype"
                            title="Matrix, chart per metric"
                            notes={[
                                'Left cell = delta, right cell = chance to win, one row per variant, lined up with the table rows.',
                                'Green or red = significant gain or loss, like the violin at full color. Gray = not significant, like the faded violin.',
                                'Stronger color = bigger change. No interval, so it shows the verdict, not the uncertainty.',
                            ]}
                        >
                            <MetricRowMatrix metric={CHECKOUT} height={3 * 56} />
                        </Panel>
                    </div>
                </Section>

                <Section
                    title="Every metric at once"
                    description="All three primary metrics. Today stacks one violin row per variant under one axis; the prototype can draw one chart."
                >
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                        <Panel
                            source="Today"
                            title="Violins on the table's shared axis"
                            notes={[
                                'One axis for the whole table, so sizes compare across metrics.',
                                'Items per order compact-cart is red and significant: a loss.',
                            ]}
                        >
                            <ProductIntervals metrics={PRIMARY_METRICS} method="bayesian" axisRange={axisRange} />
                        </Panel>
                        <div className="flex flex-col gap-3">
                            <Panel
                                source="Prototype"
                                title="Candlestick, one chart"
                                notes={[
                                    'One axis for every metric, as in today’s table. Its range fits the data instead of today’s symmetric range.',
                                    'Whiskers and a box in place of the violin.',
                                    'Color is the variant (legend), not the direction.',
                                ]}
                            >
                                <AllMetricsCandlestick metrics={PRIMARY_METRICS} colors={colors} />
                            </Panel>
                            <Panel
                                source="Prototype"
                                title="Matrix, one chart"
                                notes={[
                                    'The whole table in six cells: delta and chance to win.',
                                    'Reads fastest with many metrics; drops the interval.',
                                ]}
                            >
                                <MetricMatrix metrics={PRIMARY_METRICS} />
                            </Panel>
                        </div>
                    </div>
                </Section>

                <Section
                    title="Over time"
                    description="How the delta moved since launch. Today shows one variant per chart in the metric details; the prototype puts it in the table."
                >
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                        <Panel
                            source="Today"
                            title="Time series, one variant"
                            notes={[
                                'Line = cumulative delta for one-page. Band = its 95% interval on each day.',
                                'Line color = the variant color. The 0% goal line is the zero.',
                                'The band narrows as exposures grow; once it leaves 0% the result is significant.',
                            ]}
                        >
                            <ProductTimeseries metric={CHECKOUT} variantKey="one-page" color={colors['one-page']} />
                        </Panel>
                        <Panel
                            source="Prototype"
                            title="Delta over time, chart per metric"
                            notes={[
                                'Same line and band as today, for both test variants in one chart, in the metric row.',
                                'Variant colors match the dots in the table. Dashed line = 0%.',
                                'The axis is shared across the section, like today’s table.',
                            ]}
                        >
                            <PrototypeTrendChart
                                trends={metricTrends(CHECKOUT)}
                                colors={colors}
                                limit={limit}
                                height={200}
                                showValueAxis="yes"
                            />
                        </Panel>
                    </div>
                    <Panel
                        source="Prototype"
                        title="Delta over time, one chart"
                        notes={[
                            'Every metric and variant without bands, to compare trends.',
                            'Color = metric, line style = variant (dashed compact-cart, solid one-page).',
                            'Use the per metric chart to read the interval.',
                        ]}
                    >
                        <AllMetricsTrendChart metrics={PRIMARY_METRICS} limit={limit} />
                    </Panel>
                </Section>

                <Section
                    title="Goal: decrease"
                    description="Invented example. For Support ticket opened, fewer is better, so a drop is a win. Today and the prototype matrix both swap red and green."
                >
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
                        <Panel
                            source="Today"
                            title='Violin with goal "decrease"'
                            notes={['A −21% drop is drawn green: it is a win for this goal.']}
                        >
                            <ProductIntervals
                                metrics={[DECREASE_EXAMPLE]}
                                method="bayesian"
                                goal="decrease"
                                axisRange={0.5}
                            />
                        </Panel>
                        <Panel
                            source="Prototype"
                            title="Matrix, same result"
                            notes={['A −21% drop is green: the matrix reads the goal, not the sign of the delta.']}
                        >
                            <MetricRowMatrix metric={DECREASE_EXAMPLE} height={2 * 56} />
                        </Panel>
                    </div>
                </Section>
            </div>
        </div>
    )
}
