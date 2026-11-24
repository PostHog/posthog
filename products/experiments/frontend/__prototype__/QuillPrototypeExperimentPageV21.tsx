/**
 * Scratch prototype v21: a dense, centered results page. The side column goes; hypothesis, summary, status and
 * duration share one card next to the exposures card, and the statistics settings sit in the metrics toolbar.
 * Not committed.
 */
import { useState } from 'react'

import {
    IconChevronDown,
    IconChevronRight,
    IconEllipsis,
    IconFilter,
    IconFlask,
    IconGear,
    IconGraph,
    IconPencil,
    IconPlus,
    IconRefresh,
    IconRewindPlay,
    IconWarning,
} from '@posthog/icons'
import {
    Button,
    ButtonGroup,
    Card,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Heading,
    Progress,
    Separator,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Text,
    cn,
} from '@posthog/quill'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import {
    EXPERIMENT,
    EXPOSURES,
    HEALTH_ISSUES,
    PRIMARY_METRICS,
    PROTOTYPE_STATUS,
    type PrototypeMetric,
    type PrototypeStatus,
    type PrototypeVariantResult,
    SECONDARY_METRICS,
} from './prototypeData'
import { isSignificant, isWin } from './PrototypeMetricViews'
import {
    MetricRowChart,
    RESULT_CHART,
    RESULT_LAYOUT,
    type ResultChart,
    type ResultLayout,
    SectionResultChart,
} from './PrototypeMetricViewsV16'
import { metricTrends } from './prototypeTimeseries'
import { PrototypeTrendChart } from './PrototypeTrendChart'
import {
    ExposuresChart,
    FakePhoneHeader,
    FakeShell,
    LaunchChecklist,
    RUN_PROGRESS,
    type RunProgress,
    SceneActions,
    SceneTitle,
    SHELL_STATE,
    type ShellState,
    StatusBadge,
    VariantDot,
    axisLimit,
    formatChance,
    formatDelta,
    useVariantColors,
} from './QuillPrototypeExperimentPageV20'

export { RUN_PROGRESS, SHELL_STATE }

/** Two lines per variant row: the value and its count. */
const ROW_HEIGHT = 60

const LAYOUT_LABEL: Record<ResultLayout, string> = { 'per-metric': 'Chart per metric', 'all-metrics': 'One chart' }
const CHART_LABEL: Record<ResultChart, string> = {
    trend: 'Delta over time',
    candlestick: 'Candlestick',
    matrix: 'Matrix',
}

const METRIC_ACTIONS = [
    { key: 'details', label: 'Details', icon: <IconGraph /> },
    { key: 'recordings', label: 'View recordings', icon: <IconRewindPlay /> },
    { key: 'breakdowns', label: 'Breakdown by', icon: <IconFilter /> },
    { key: 'edit', label: 'Edit metric', icon: <IconPencil /> },
] as const

function FieldLabel({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <Text size="xs" weight="medium" variant="muted" render={<span className="uppercase tracking-wide" />}>
            {children}
        </Text>
    )
}

/** Hypothesis, then the facts a reader checks first: what to do, whether the run is healthy, how long it has run. */
function OverviewCard({ status, progress }: { status: PrototypeStatus; progress: RunProgress }): JSX.Element {
    const colors = useVariantColors()
    const isDraft = status === PROTOTYPE_STATUS.draft
    const targetReached = progress === RUN_PROGRESS.targetReached
    return (
        <Card size="sm" className="gap-3 p-4" data-attr="overview-card">
            <div className="flex flex-col gap-1.5">
                <span className="flex items-center gap-1">
                    <FieldLabel>Hypothesis</FieldLabel>
                    <Button size="icon-xs" aria-label="Edit hypothesis" tooltip="Edit hypothesis">
                        <IconPencil />
                    </Button>
                </span>
                <Text size="sm" render={<p className="m-0" />}>
                    {EXPERIMENT.hypothesis}
                </Text>
            </div>
            <Separator />
            <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-6 gap-y-2.5">
                <dt>
                    <FieldLabel>Summary</FieldLabel>
                </dt>
                <dd className="m-0 flex flex-wrap items-center gap-x-2 gap-y-1">
                    {isDraft ? (
                        <Text size="sm" variant="muted" render={<span />}>
                            Results show after launch.
                        </Text>
                    ) : (
                        <>
                            <VariantDot color={colors['one-page']} />
                            <Text size="sm" render={<span />}>
                                <span className="font-semibold">
                                    one-page {targetReached ? 'won' : 'leads'} on Checkout completed.
                                </span>{' '}
                                {targetReached ? 'Release it.' : 'About 5 days left.'}
                            </Text>
                            {targetReached && (
                                <Button size="sm" variant="primary" data-attr="summary-release-variant">
                                    Release one-page
                                </Button>
                            )}
                        </>
                    )}
                </dd>
                <dt>
                    <FieldLabel>Status</FieldLabel>
                </dt>
                <dd className="m-0 flex items-center gap-3">
                    <StatusBadge status={status} />
                    {status === PROTOTYPE_STATUS.running && (
                        <Button
                            variant="link"
                            size="inline"
                            className="text-warning-foreground"
                            data-attr="health-link"
                        >
                            <IconWarning />
                            {HEALTH_ISSUES.length} health issues
                        </Button>
                    )}
                </dd>
                <dt>
                    <FieldLabel>Duration</FieldLabel>
                </dt>
                <dd className="m-0 flex items-center gap-3">
                    {isDraft ? (
                        <Text size="sm" variant="muted" render={<span />}>
                            About 14 days at current traffic
                        </Text>
                    ) : (
                        <>
                            <Progress value={targetReached ? 100 : 64} variant="success" className="w-40" />
                            <Text size="sm" variant="muted" render={<span />}>
                                {targetReached ? 'Target reached after 14 days' : 'Day 9 of about 14'}
                            </Text>
                        </>
                    )}
                </dd>
            </dl>
        </Card>
    )
}

function ExposuresCard({ status }: { status: PrototypeStatus }): JSX.Element {
    const colors = useVariantColors()
    const isDraft = status === PROTOTYPE_STATUS.draft
    return (
        <Card size="sm" className="gap-2 p-4" data-attr="exposures-card">
            <span className="flex items-baseline gap-3">
                <FieldLabel>Exposures</FieldLabel>
                {!isDraft && (
                    <Text size="base" weight="semibold" render={<span className="tabular-nums" />}>
                        {EXPOSURES.total}
                    </Text>
                )}
                <Button
                    size="icon-xs"
                    className="ml-auto"
                    aria-label="Edit exposure criteria"
                    tooltip="Edit exposure criteria"
                >
                    <IconPencil />
                </Button>
            </span>
            {isDraft ? (
                <Text size="sm" variant="muted" render={<p className="m-0" />}>
                    {EXPOSURES.criteria}. Counts show after launch. Target split 33% each.
                </Text>
            ) : (
                <>
                    <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                        {EXPOSURES.split.map((row) => (
                            <span key={row.key} className="flex items-center gap-1.5">
                                <VariantDot color={colors[row.key]} />
                                <Text size="xs" weight="medium" render={<span />}>
                                    {row.key}
                                </Text>
                                <Text size="xs" variant="muted" render={<span className="tabular-nums" />}>
                                    {row.share}
                                </Text>
                            </span>
                        ))}
                    </span>
                    <ExposuresChart />
                </>
            )}
        </Card>
    )
}

/** Both view choices in one menu, so the toolbar keeps one button for them. */
function ViewMenu({
    layout,
    chart,
    onLayoutChange,
    onChartChange,
}: {
    layout: ResultLayout
    chart: ResultChart
    onLayoutChange: (layout: ResultLayout) => void
    onChartChange: (chart: ResultChart) => void
}): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="outline" size="sm" data-attr="result-view-menu" />}>
                {CHART_LABEL[chart]}
                {layout === RESULT_LAYOUT.allMetrics && <span className="text-muted-foreground">· one chart</span>}
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Chart</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={chart}
                        onValueChange={(value) => onChartChange(value as ResultChart)}
                    >
                        {Object.values(RESULT_CHART).map((value) => (
                            <DropdownMenuRadioItem key={value} value={value}>
                                {CHART_LABEL[value]}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Layout</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={layout}
                        onValueChange={(value) => onLayoutChange(value as ResultLayout)}
                    >
                        {Object.values(RESULT_LAYOUT).map((value) => (
                            <DropdownMenuRadioItem key={value} value={value}>
                                {LAYOUT_LABEL[value]}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function MetricsToolbar({ status, view }: { status: PrototypeStatus; view: React.ReactNode }): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr="metrics-toolbar">
            {status !== PROTOTYPE_STATUS.draft && view}
            <ButtonGroup>
                <Button variant="outline" size="sm">
                    {EXPERIMENT.statsMethod}
                </Button>
                <Button variant="outline" size="sm">
                    {EXPERIMENT.confidence}
                </Button>
                <Button variant="outline" size="icon-sm" aria-label="Statistics settings" tooltip="Statistics settings">
                    <IconGear />
                </Button>
            </ButtonGroup>
            <Button variant="outline" size="sm">
                <IconPlus />
                Add metric
            </Button>
            {status === PROTOTYPE_STATUS.running && (
                <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    tooltip="Refresh results"
                    data-attr="refresh-results"
                >
                    <IconRefresh />9 min ago
                </Button>
            )}
        </div>
    )
}

function MetricMenu({ name }: { name: string }): JSX.Element {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-xs"
                        aria-label={`Actions for ${name}`}
                        tooltip="Metric actions"
                        className="opacity-0 transition-opacity group-hover/metric:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100 motion-reduce:transition-none"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {METRIC_ACTIONS.map((action) => (
                    <DropdownMenuItem key={action.key}>
                        {action.icon}
                        {action.label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/** A light tint on a variant that significantly moves the metric the right way, as the strongest cue in the table. */
const WIN_ROW = { backgroundColor: 'color-mix(in oklab, var(--success-foreground) 7%, transparent)' }
const WIN_CELL = { backgroundColor: 'color-mix(in oklab, var(--success-foreground) 14%, transparent)' }

function DeltaText({ variant, metric }: { variant: PrototypeVariantResult; metric: PrototypeMetric }): JSX.Element {
    if (variant.delta === null) {
        return <span />
    }
    const significant = isSignificant(variant)
    const win = isWin(variant, metric.goal)
    return (
        <Text
            size="sm"
            weight={significant ? 'semibold' : 'normal'}
            render={
                <span
                    className={cn(
                        'tabular-nums',
                        significant && win && 'text-success-foreground',
                        significant && !win && 'text-destructive-foreground'
                    )}
                />
            }
        >
            {formatDelta(variant.delta)}
        </Text>
    )
}

function MetricRows({
    metric,
    colors,
    limit,
    isDraft,
    layout,
    chart,
}: {
    metric: PrototypeMetric
    colors: Record<string, string>
    limit: number
    isDraft: boolean
    layout: ResultLayout
    chart: ResultChart
}): JSX.Element {
    const rowChart = layout === RESULT_LAYOUT.perMetric && !isDraft
    const chartHeight = metric.variants.length * ROW_HEIGHT - 16
    return (
        <>
            {metric.variants.map((variant, variantIndex) => {
                const winning =
                    !isDraft && variant.delta !== null && isSignificant(variant) && isWin(variant, metric.goal)
                const last = variantIndex === metric.variants.length - 1
                /** Lines only between metrics, so one metric's variants read as one block. */
                const rowStyle: React.CSSProperties = {
                    ...(winning ? WIN_ROW : {}),
                    ...(last ? {} : { borderBottom: 'none' }),
                }
                return (
                    <TableRow key={variant.key} style={{ height: isDraft ? 36 : ROW_HEIGHT }}>
                        {variantIndex === 0 && (
                            <TableCell
                                rowSpan={metric.variants.length}
                                className="group/metric border-r border-border align-top"
                                style={{ width: 240, minWidth: 240 }}
                            >
                                <div className="flex items-start gap-1 pt-1">
                                    <IconChevronRight className="mt-0.5 shrink-0 text-muted-foreground" />
                                    <div className="flex min-w-0 flex-1 flex-col">
                                        <Text size="sm" weight="semibold" render={<span />}>
                                            {metric.name}
                                        </Text>
                                        <Text size="xs" variant="muted" render={<span />}>
                                            {metric.kind}
                                        </Text>
                                    </div>
                                    {!isDraft && <MetricMenu name={metric.name} />}
                                </div>
                            </TableCell>
                        )}
                        <TableCell style={rowStyle}>
                            <span className="flex items-center gap-2 whitespace-nowrap">
                                <VariantDot color={colors[variant.key]} />
                                <Text size="sm" render={<span />}>
                                    {variant.key}
                                </Text>
                            </span>
                        </TableCell>
                        {isDraft ? (
                            variantIndex === 0 && (
                                <TableCell colSpan={4} rowSpan={metric.variants.length} className="align-middle">
                                    <Text size="sm" variant="muted" render={<span />}>
                                        Results show after launch
                                    </Text>
                                </TableCell>
                            )
                        ) : (
                            <>
                                <TableCell className="whitespace-nowrap" style={rowStyle}>
                                    <Text size="sm" weight="medium" render={<span className="block tabular-nums" />}>
                                        {variant.value}
                                    </Text>
                                    <Text size="xs" variant="muted" render={<span className="block tabular-nums" />}>
                                        {variant.detail}
                                    </Text>
                                </TableCell>
                                <TableCell style={rowStyle}>
                                    <DeltaText variant={variant} metric={metric} />
                                </TableCell>
                                <TableCell style={winning ? { ...rowStyle, ...WIN_CELL } : rowStyle}>
                                    <Text
                                        size="sm"
                                        weight={winning ? 'semibold' : 'normal'}
                                        render={
                                            <span
                                                className={cn('tabular-nums', winning && 'text-success-foreground')}
                                            />
                                        }
                                    >
                                        {variant.chanceToWin === null ? '' : formatChance(variant.chanceToWin)}
                                    </Text>
                                </TableCell>
                                {rowChart && variantIndex === 0 && (
                                    <TableCell
                                        rowSpan={metric.variants.length}
                                        className="hidden @4xl/main-content:table-cell"
                                        style={{ paddingLeft: 16 }}
                                    >
                                        <MetricRowChart
                                            chart={chart}
                                            metric={metric}
                                            height={chartHeight}
                                            trend={
                                                <PrototypeTrendChart
                                                    trends={metricTrends(metric)}
                                                    colors={colors}
                                                    limit={limit}
                                                    height={chartHeight}
                                                    showValueAxis="yes"
                                                />
                                            }
                                        />
                                    </TableCell>
                                )}
                            </>
                        )}
                    </TableRow>
                )
            })}
        </>
    )
}

function MetricsSection({
    title,
    metrics,
    status,
    layout,
    chart,
    toolbar,
}: {
    title: string
    metrics: PrototypeMetric[]
    status: PrototypeStatus
    layout: ResultLayout
    chart: ResultChart
    toolbar?: React.ReactNode
}): JSX.Element {
    const colors = useVariantColors()
    const isDraft = status === PROTOTYPE_STATUS.draft
    const rowChart = layout === RESULT_LAYOUT.perMetric && !isDraft
    const limit = axisLimit(metrics)
    return (
        <section className="flex flex-col gap-2.5" data-attr={`metrics-${title.toLowerCase().replace(' ', '-')}`}>
            <Heading size="lg" render={<h2 className="m-0" />}>
                {title}
            </Heading>
            {toolbar}
            {!isDraft && !rowChart && (
                <SectionResultChart chart={chart} title={title} metrics={metrics} colors={colors} limit={limit} />
            )}
            <Card size="sm" flush className="overflow-clip">
                <Table size="sm" fullWidth stickyHeader="page">
                    <TableHeader>
                        <TableRow>
                            <TableHead>Metric</TableHead>
                            <TableHead>Variant</TableHead>
                            {!isDraft && (
                                <>
                                    <TableHead>Value</TableHead>
                                    <TableHead>Delta</TableHead>
                                    <TableHead>Win %</TableHead>
                                    {rowChart && (
                                        <TableHead expand className="hidden @4xl/main-content:table-cell">
                                            {chart === RESULT_CHART.trend ? (
                                                <span className="flex justify-between font-normal normal-case">
                                                    <span>Nov 3</span>
                                                    <span>Nov 16</span>
                                                </span>
                                            ) : (
                                                CHART_LABEL[chart]
                                            )}
                                        </TableHead>
                                    )}
                                </>
                            )}
                            {isDraft && <TableHead expand />}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {metrics.map((metric) => (
                            <MetricRows
                                key={metric.name}
                                metric={metric}
                                colors={colors}
                                limit={limit}
                                isDraft={isDraft}
                                layout={layout}
                                chart={chart}
                            />
                        ))}
                    </TableBody>
                </Table>
            </Card>
        </section>
    )
}

function ResultsTab({
    status,
    progress,
    resultLayout,
    resultChart,
}: {
    status: PrototypeStatus
    progress: RunProgress
    resultLayout: ResultLayout
    resultChart: ResultChart
}): JSX.Element {
    const [layout, setLayout] = useState<ResultLayout>(resultLayout)
    const [chart, setChart] = useState<ResultChart>(resultChart)
    return (
        <div className="flex flex-col gap-6">
            {status === PROTOTYPE_STATUS.draft && <LaunchChecklist />}
            <div className="grid grid-cols-1 gap-4 @4xl/main-content:grid-cols-2">
                <OverviewCard status={status} progress={progress} />
                <ExposuresCard status={status} />
            </div>
            <MetricsSection
                title="Primary metrics"
                metrics={PRIMARY_METRICS}
                status={status}
                layout={layout}
                chart={chart}
                toolbar={
                    <MetricsToolbar
                        status={status}
                        view={
                            <ViewMenu
                                layout={layout}
                                chart={chart}
                                onLayoutChange={setLayout}
                                onChartChange={setChart}
                            />
                        }
                    />
                }
            />
            <MetricsSection
                title="Secondary metrics"
                metrics={SECONDARY_METRICS}
                status={status}
                layout={layout}
                chart={chart}
            />
        </div>
    )
}

const TABS = [
    ['results', 'Results'],
    ['health', 'Health'],
    ['recordings', 'Recordings'],
    ['feedback', 'User feedback'],
    ['settings', 'Settings'],
    ['variants', 'Variants'],
    ['code', 'Code'],
    ['history', 'History'],
] as const

export function QuillPrototypeExperimentPageV21({
    status,
    shell,
    progress,
    resultLayout = RESULT_LAYOUT.perMetric,
    resultChart = RESULT_CHART.trend,
}: {
    status: PrototypeStatus
    shell: ShellState
    progress: RunProgress
    resultLayout?: ResultLayout
    resultChart?: ResultChart
}): JSX.Element {
    return (
        <div data-quill className="flex h-screen bg-background text-foreground">
            <FakeShell shell={shell} />
            <main className="@container/main-content flex min-w-0 flex-1 flex-col">
                {shell === SHELL_STATE.phone && <FakePhoneHeader />}
                <QuillSceneHeader
                    icon={<IconFlask />}
                    title={<SceneTitle />}
                    actions={<SceneActions status={status} />}
                />
                <Tabs defaultValue="results" className="flex min-h-0 flex-1 flex-col gap-0">
                    <div className="shrink-0 border-b border-border px-4">
                        <TabsList variant="line">
                            {TABS.map(([key, label]) => (
                                <TabsTrigger key={key} value={key}>
                                    {label}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                    </div>
                    <div
                        data-attr="prototype-scroll"
                        className="flex-1 overflow-y-auto"
                        style={{ '--quill-table-sticky-top': '0px' } as React.CSSProperties}
                    >
                        <TabsContent value="results" className="mx-auto w-full max-w-6xl px-4 py-5">
                            <ResultsTab
                                status={status}
                                progress={progress}
                                resultLayout={resultLayout}
                                resultChart={resultChart}
                            />
                        </TabsContent>
                    </div>
                </Tabs>
            </main>
        </div>
    )
}
