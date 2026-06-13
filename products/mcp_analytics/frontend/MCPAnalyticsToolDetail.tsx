import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconArrowLeft, IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import {
    type ChartTheme,
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
} from '@posthog/quill-charts'
import { Skeleton, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'

import { buildTheme } from 'lib/charts/utils/theme'
import { TZLabel } from 'lib/components/TZLabel'
import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDuration, humanFriendlyNumber } from 'lib/utils'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { SceneExport } from '~/scenes/sceneTypes'

import { HarnessPill } from './dashboard/harness'
import {
    type DailyChartData,
    IntentCoverage,
    MCPAnalyticsToolDetailLogicProps,
    type ResultRows,
    ToolSummary,
    mcpAnalyticsToolDetailLogic,
} from './mcpAnalyticsToolDetailLogic'
import { categorizeHarness } from './mcpDashboardOverviewLogic'

export const scene: SceneExport<MCPAnalyticsToolDetailLogicProps> = {
    component: MCPAnalyticsToolDetail,
    logic: mcpAnalyticsToolDetailLogic,
    paramsToProps: ({ params: { toolName } }) => ({
        toolName: decodeURIComponent(toolName ?? ''),
    }),
}

function percentDelta(current: number, previous: number): number | null {
    if (!previous) {
        return null
    }
    return ((current - previous) / previous) * 100
}

function DeltaTag({ value, invertColor = false }: { value: number | null; invertColor?: boolean }): JSX.Element | null {
    if (value == null || !isFinite(value) || Math.abs(value) < 1) {
        return null
    }
    const positive = value > 0
    // For error rate, "up" is bad — invert color semantics.
    const goodDirection = invertColor ? !positive : positive
    const Icon = positive ? IconArrowUp : IconArrowDown
    return (
        <span
            className={`inline-flex items-center gap-0.5 text-xs leading-none ${
                goodDirection ? 'text-success' : 'text-danger'
            }`}
        >
            <Icon className="text-sm" />
            {Math.abs(Math.round(value))}%
        </span>
    )
}

function Stat({
    label,
    value,
    delta,
    deltaInvertColor,
    loading,
    tooltip,
}: {
    label: string
    value: React.ReactNode
    delta?: number | null
    deltaInvertColor?: boolean
    loading?: boolean
    tooltip?: string
}): JSX.Element {
    const content = (
        <div className="flex flex-col gap-1 min-w-[110px]">
            <span className="text-[11px] uppercase tracking-wider text-secondary">{label}</span>
            {loading ? (
                <LemonSkeleton className="h-6 w-16" />
            ) : (
                <div className="flex items-baseline gap-2">
                    <span className="text-2xl font-semibold leading-none">{value}</span>
                    <DeltaTag value={delta ?? null} invertColor={deltaInvertColor} />
                </div>
            )}
        </div>
    )
    return tooltip ? <Tooltip title={tooltip}>{content}</Tooltip> : content
}

// Renderer for the "person" column in the Top users table. The query selects
// `argMax(tuple(distinct_id, person.created_at, person.properties), timestamp)`,
// which deserialises as a 3-element array. Wrap it back into the shape PersonDisplay expects.
function renderPersonCell(value: unknown): JSX.Element {
    if (!Array.isArray(value) || value.length === 0) {
        return <span className="text-muted">—</span>
    }
    const [distinctId, , propertiesRaw] = value as [string, unknown, unknown]
    let properties: Record<string, unknown> | undefined
    if (propertiesRaw && typeof propertiesRaw === 'object') {
        properties = propertiesRaw as Record<string, unknown>
    } else if (typeof propertiesRaw === 'string') {
        try {
            properties = JSON.parse(propertiesRaw)
        } catch {
            properties = undefined
        }
    }
    return (
        <PersonDisplay person={{ distinct_id: distinctId, properties: properties ?? {} }} withIcon noPopover={false} />
    )
}

interface ResultColumn {
    header: string
    align?: 'left' | 'right'
    expand?: boolean
    render: (row: unknown[]) => React.ReactNode
}

const neighborColumns: ResultColumn[] = [
    { header: 'Tool', expand: true, render: (r) => <span className="font-mono">{String(r[0] ?? '')}</span> },
    { header: 'In same conversation', align: 'right', render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)) },
]

// Renders raw HogQL result rows (positional columns) as a quill table, with loading/empty states.
function ResultTable({
    rows,
    loading,
    columns,
    emptyMessage = 'No data for the last 7 days.',
}: {
    rows: ResultRows
    loading: boolean
    columns: ResultColumn[]
    emptyMessage?: string
}): JSX.Element {
    return (
        <div data-quill>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        {columns.map((col, i) => (
                            <TableHead key={i} align={col.align} expand={col.expand}>
                                {col.header}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {loading && rows.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={columns.length}>
                                <div className="space-y-2 py-1">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                        <Skeleton key={i} className="h-3.5 w-full" />
                                    ))}
                                </div>
                            </TableCell>
                        </TableRow>
                    ) : rows.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={columns.length} align="center" className="py-6 text-secondary">
                                {emptyMessage}
                            </TableCell>
                        </TableRow>
                    ) : (
                        rows.map((row, i) => (
                            <TableRow key={i}>
                                {columns.map((col, ci) => (
                                    <TableCell key={ci} align={col.align} expand={col.expand}>
                                        {col.render(row)}
                                    </TableCell>
                                ))}
                            </TableRow>
                        ))
                    )}
                </TableBody>
            </Table>
        </div>
    )
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-0.5">
            <h2 className="text-base font-semibold mb-0">{title}</h2>
            {subtitle ? <span className="text-xs text-secondary">{subtitle}</span> : null}
        </div>
    )
}

function formatDurationMs(ms: number | null): string {
    if (ms == null) {
        return '—'
    }
    if (ms < 1000) {
        return `${Math.round(ms)} ms`
    }
    return humanFriendlyDuration(ms / 1000, { secondsFixed: 2 })
}

function StatStrip({ summary, loading }: { summary: ToolSummary | null; loading: boolean }): JSX.Element {
    const calls = summary?.calls ?? 0
    const errors = summary?.errors ?? 0
    const errorRate = calls ? (errors / calls) * 100 : 0
    const errorRatePrev = summary && summary.calls_prev ? (summary.errors_prev / summary.calls_prev) * 100 : 0
    return (
        <div className="flex flex-wrap items-end gap-x-10 gap-y-4 py-1">
            <Stat
                label="Calls"
                loading={loading}
                value={humanFriendlyNumber(calls)}
                delta={summary ? percentDelta(calls, summary.calls_prev) : null}
                tooltip="Last 7 days vs prior 7 days."
            />
            <Stat
                label="Error rate"
                loading={loading}
                value={`${errorRate.toFixed(1)}%`}
                delta={summary ? percentDelta(errorRate, errorRatePrev) : null}
                deltaInvertColor
                tooltip="Share of calls with $mcp_is_error = true."
            />
            <Stat label="p50 latency" loading={loading} value={formatDurationMs(summary?.p50_ms ?? null)} />
            <Stat label="p95 latency" loading={loading} value={formatDurationMs(summary?.p95_ms ?? null)} />
            <Stat label="Users" loading={loading} value={humanFriendlyNumber(summary?.users ?? 0)} />
            <Stat
                label="Sessions"
                loading={loading}
                value={humanFriendlyNumber(summary?.conversations ?? 0)}
                tooltip="Unique $mcp_session_id values, falling back to $session_id where missing."
            />
        </div>
    )
}

function IntentCoverageTag({
    coverage,
    loading,
}: {
    coverage: IntentCoverage | null
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-4 w-32" />
    }
    if (!coverage || !coverage.total) {
        return null
    }
    const pct = Math.round((coverage.with_intent / coverage.total) * 100)
    return (
        <Tooltip title="Share of calls where $mcp_intent was captured. Inferred intents are server fallbacks; context_parameter intents come from the client.">
            <span className="text-[11px] text-secondary">
                {humanFriendlyNumber(coverage.with_intent)} of {humanFriendlyNumber(coverage.total)} calls captured
                intent ({pct}%)
            </span>
        </Tooltip>
    )
}

function DescriptionBlock({
    descriptions,
    loading,
}: {
    descriptions: { description: string; last_seen: string }[]
    loading: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-8 w-2/3 mt-2" />
    }
    if (!descriptions.length) {
        return null
    }
    const [latest, ...older] = descriptions
    return (
        <div className="flex flex-col gap-1 max-w-3xl">
            <span className="text-[11px] uppercase tracking-wider text-secondary">Description</span>
            <LemonMarkdown className="text-sm leading-snug" lowKeyHeadings>
                {latest.description}
            </LemonMarkdown>
            {older.length > 0 ? (
                <Tooltip
                    title={
                        <div className="flex flex-col gap-2 max-w-md">
                            {older.map((d) => (
                                <div key={d.last_seen} className="text-xs">
                                    <div className="text-secondary mb-0.5">
                                        last seen <TZLabel time={d.last_seen} />
                                    </div>
                                    <LemonMarkdown lowKeyHeadings>{d.description}</LemonMarkdown>
                                </div>
                            ))}
                        </div>
                    }
                >
                    <span className="text-[11px] text-secondary underline decoration-dotted cursor-help w-fit">
                        + {older.length} previous version{older.length === 1 ? '' : 's'}
                    </span>
                </Tooltip>
            ) : null}
        </div>
    )
}

function trendChartConfig(timezone: string, yAxis?: TimeSeriesLineChartConfig['yAxis']): TimeSeriesLineChartConfig {
    return {
        yAxis: { showGrid: false, ...yAxis },
        showAxisLines: true,
        xAxis: { interval: 'day', timezone },
        showCrosshair: true,
        tooltip: { placement: 'cursor' },
    }
}

type TrendSeriesKey = 'calls' | 'errors' | 'p50' | 'p95'
const SERIES_META: Record<TrendSeriesKey, { label: string; colorIndex: number }> = {
    calls: { label: 'Calls', colorIndex: 0 },
    errors: { label: 'Errors', colorIndex: 4 },
    p50: { label: 'p50', colorIndex: 1 },
    p95: { label: 'p95', colorIndex: 0 },
}

function seriesFor(data: DailyChartData, theme: ChartTheme, keys: TrendSeriesKey[]): Series[] {
    return keys.map((key) => ({
        key,
        label: SERIES_META[key].label,
        color: theme.colors[SERIES_META[key].colorIndex],
        data: data[key],
    }))
}

function formatMsAxis(ms: number): string {
    if (!isFinite(ms)) {
        return '—'
    }
    return ms < 1000 ? `${Math.round(ms)}ms` : `${Math.round(ms / 100) / 10}s`
}

function TrendChart({
    title,
    series,
    labels,
    config,
    theme,
    loading,
    dataAttr,
}: {
    title: string
    series: Series[]
    labels: string[]
    config: TimeSeriesLineChartConfig
    theme: ChartTheme
    loading: boolean
    dataAttr: string
}): JSX.Element {
    return (
        <div className="flex flex-col rounded border bg-bg-light p-2" style={{ height: 240 }} data-quill>
            <div className="mb-1 px-2 pt-1 text-xs font-medium uppercase text-secondary">{title}</div>
            <div className="flex min-h-0 flex-1 flex-col">
                {loading && labels.length === 0 ? (
                    <Skeleton className="flex-1" />
                ) : labels.length === 0 ? (
                    <div className="flex flex-1 items-center justify-center text-[12px] text-secondary">
                        No data for the last 7 days.
                    </div>
                ) : (
                    <TimeSeriesLineChart
                        series={series}
                        labels={labels}
                        config={config}
                        theme={theme}
                        dataAttr={dataAttr}
                    />
                )}
            </div>
        </div>
    )
}

export function MCPAnalyticsToolDetail({ toolName }: { toolName: string }): JSX.Element {
    const {
        summary,
        summaryLoading,
        descriptions,
        descriptionsLoading,
        dailyChartData,
        dailyStatsLoading,
        failureRows,
        failureRowsLoading,
        sampleIntentRows,
        sampleIntentRowsLoading,
        intentCoverage,
        intentCoverageLoading,
        neighborsBeforeRows,
        neighborsBeforeRowsLoading,
        neighborsAfterRows,
        neighborsAfterRowsLoading,
        byHarnessRows,
        byHarnessRowsLoading,
        topUserRows,
        topUserRowsLoading,
    } = useValues(mcpAnalyticsToolDetailLogic({ toolName }))
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    // buildTheme() reads CSS vars from the DOM; isDarkModeOn forces a recompute on theme flip.
    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])
    const callsSeries = useMemo<Series[]>(
        () => seriesFor(dailyChartData, theme, ['calls', 'errors']),
        [dailyChartData, theme]
    )
    const latencySeries = useMemo<Series[]>(
        () => seriesFor(dailyChartData, theme, ['p50', 'p95']),
        [dailyChartData, theme]
    )
    const countsConfig = useMemo(() => trendChartConfig(timezone), [timezone])
    const latencyConfig = useMemo(() => trendChartConfig(timezone, { tickFormatter: formatMsAxis }), [timezone])

    return (
        <SceneContent>
            <SceneTitleSection
                name={toolName}
                description={null}
                resourceType={{ type: 'llm_analytics' }}
                actions={
                    <LemonButton
                        icon={<IconArrowLeft />}
                        type="secondary"
                        size="small"
                        to={urls.mcpAnalyticsToolQuality()}
                    >
                        Back to Tool quality
                    </LemonButton>
                }
            />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <DescriptionBlock descriptions={descriptions} loading={descriptionsLoading} />
                <StatStrip summary={summary} loading={summaryLoading} />
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Reliability" subtitle="Last 7 days" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <TrendChart
                        title="Calls and errors"
                        series={callsSeries}
                        labels={dailyChartData.labels}
                        config={countsConfig}
                        theme={theme}
                        loading={dailyStatsLoading}
                        dataAttr="mcp-tool-detail-calls-chart"
                    />
                    <TrendChart
                        title="Duration (p50 / p95)"
                        series={latencySeries}
                        labels={dailyChartData.labels}
                        config={latencyConfig}
                        theme={theme}
                        loading={dailyStatsLoading}
                        dataAttr="mcp-tool-detail-latency-chart"
                    />
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Usage flow" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="flex flex-col gap-2 bg-bg-light border rounded p-3">
                        <div className="flex items-center justify-between gap-2">
                            <span className="text-xs font-medium uppercase text-secondary">Sample intents</span>
                            <IntentCoverageTag coverage={intentCoverage} loading={intentCoverageLoading} />
                        </div>
                        <ResultTable
                            rows={sampleIntentRows}
                            loading={sampleIntentRowsLoading}
                            emptyMessage="No intents captured in the last 7 days."
                            columns={[
                                { header: 'When', render: (r) => <TZLabel time={String(r[0])} /> },
                                { header: 'Intent', expand: true, render: (r) => <span>{String(r[1] ?? '')}</span> },
                                { header: 'Intent source', render: (r) => <span>{String(r[2] ?? '')}</span> },
                                { header: 'Harness', render: (r) => <span>{String(r[3] ?? '')}</span> },
                            ]}
                        />
                    </div>
                    <div className="flex flex-col gap-3">
                        <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                            <div className="flex items-center gap-1 text-xs font-medium uppercase text-secondary">
                                <IconArrowLeft className="text-base" />
                                Often called before (same conversation)
                            </div>
                            <ResultTable
                                rows={neighborsBeforeRows}
                                loading={neighborsBeforeRowsLoading}
                                emptyMessage="No tools commonly precede this one."
                                columns={neighborColumns}
                            />
                        </div>
                        <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                            <div className="flex items-center gap-1 text-xs font-medium uppercase text-secondary">
                                <IconArrowRight className="text-base" />
                                Often called after (same conversation)
                            </div>
                            <ResultTable
                                rows={neighborsAfterRows}
                                loading={neighborsAfterRowsLoading}
                                emptyMessage="No tools commonly follow this one."
                                columns={neighborColumns}
                            />
                        </div>
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader title="Who uses it" />
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                        <span className="text-xs font-medium uppercase text-secondary">By harness</span>
                        <ResultTable
                            rows={byHarnessRows}
                            loading={byHarnessRowsLoading}
                            columns={[
                                {
                                    header: 'Harness',
                                    expand: true,
                                    render: (r) => {
                                        const raw = String(r[0] ?? '')
                                        return raw ? (
                                            <HarnessPill category={categorizeHarness(raw)} title={raw} />
                                        ) : (
                                            <span className="text-muted">Unknown</span>
                                        )
                                    },
                                },
                                {
                                    header: 'Calls',
                                    align: 'right',
                                    render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                                },
                                {
                                    header: 'Errors',
                                    align: 'right',
                                    render: (r) => humanFriendlyNumber(Number(r[2] ?? 0)),
                                },
                                { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                                {
                                    header: 'Users',
                                    align: 'right',
                                    render: (r) => humanFriendlyNumber(Number(r[4] ?? 0)),
                                },
                            ]}
                        />
                    </div>
                    <div className="bg-bg-light border rounded p-3 flex flex-col gap-2">
                        <span className="text-xs font-medium uppercase text-secondary">Top users</span>
                        <ResultTable
                            rows={topUserRows}
                            loading={topUserRowsLoading}
                            columns={[
                                { header: 'User', expand: true, render: (r) => renderPersonCell(r[0]) },
                                {
                                    header: 'Calls',
                                    align: 'right',
                                    render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                                },
                                {
                                    header: 'Errors',
                                    align: 'right',
                                    render: (r) => humanFriendlyNumber(Number(r[2] ?? 0)),
                                },
                                { header: 'Error rate', align: 'right', render: (r) => `${Number(r[3] ?? 0)}%` },
                                {
                                    header: 'Harnesses',
                                    render: (r) => <span className="text-secondary">{String(r[4] ?? '')}</span>,
                                },
                                { header: 'Last seen', render: (r) => <TZLabel time={String(r[5])} /> },
                            ]}
                        />
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="flex flex-col gap-3 px-4 pb-4">
                <SectionHeader
                    title="Failures"
                    subtitle="Top exception messages paired with this tool. Sourced from $exception events."
                />
                <ResultTable
                    rows={failureRows}
                    loading={failureRowsLoading}
                    emptyMessage="No exceptions recorded for this tool in the last 7 days."
                    columns={[
                        {
                            header: 'Message',
                            expand: true,
                            render: (r) => <span className="font-mono text-xs">{String(r[0] ?? '')}</span>,
                        },
                        {
                            header: 'Occurrences',
                            align: 'right',
                            render: (r) => humanFriendlyNumber(Number(r[1] ?? 0)),
                        },
                        { header: 'Last seen', render: (r) => <TZLabel time={String(r[2])} /> },
                        {
                            header: 'Harnesses',
                            render: (r) => <span className="text-secondary">{String(r[3] ?? '')}</span>,
                        },
                    ]}
                />
            </div>
        </SceneContent>
    )
}

export default MCPAnalyticsToolDetail
