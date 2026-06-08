import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import {
    BarChart,
    type BarChartConfig,
    type ChartTheme,
    MetricCard,
    PieChart,
    type PieChartConfig,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    type TooltipContext,
    useRadialLayout,
    ValueLabels,
} from '@posthog/quill-charts'
import { Badge, cn, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@posthog/quill-primitives'
import '@posthog/quill-primitives/styles.css'

import { buildTheme } from 'lib/charts/utils/theme'
import { humanFriendlyDuration, humanFriendlyLargeNumber } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import claudeLogo from './harness-logos/claude.svg'
import cursorLogo from './harness-logos/cursor.svg'
import openaiLogo from './harness-logos/openai.svg'
import vscodeLogo from './harness-logos/vscode.svg'
import {
    type DailyActivity,
    HarnessRow,
    KPIMetric,
    NotableSession,
    type ToolDailySeries,
    ToolRow,
    mcpDashboardOverviewLogic,
} from './mcpDashboardOverviewLogic'

const HARNESS_LOGOS: Record<string, string> = {
    'Claude Code': claudeLogo,
    'Claude.ai': claudeLogo,
    'OpenAI Codex': openaiLogo,
    Cursor: cursorLogo,
    'VS Code': vscodeLogo,
}

// Deliberate slice color per harness, picked so the logo drawn on top has enough contrast:
// coral Claude on cool blue/teal, teal OpenAI on purple, black Cursor on light amber, blue VS Code
// on orange. Index into the data-viz palette; unknown harnesses fall back to their position.
const HARNESS_SLICE_COLOR_INDEX: Record<string, number> = {
    'Claude Code': 0, // blue
    'Claude.ai': 2, // teal
    'OpenAI Codex': 1, // purple
    Cursor: 12, // amber
    'VS Code': 11, // orange
}

export function HarnessPill({ category, title }: { category: string; title?: string }): JSX.Element {
    const logo = HARNESS_LOGOS[category]
    return (
        <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary bg-surface-primary px-2 py-0.5 text-xs"
            title={title}
        >
            {logo ? (
                <img src={logo} alt="" className="h-3.5 w-3.5 shrink-0 object-contain" />
            ) : (
                <span className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-secondary" aria-hidden />
            )}
            <span className="truncate">{category}</span>
        </span>
    )
}

interface TileSpec {
    label: string
    metric: KPIMetric
    href: string
    format: (n: number) => string
    /** Sparkline color, picked from the shared data-viz palette (theme.colors). */
    color: string
    loading: boolean
}

function formatNumber(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return humanFriendlyLargeNumber(n)
}

function formatPercent(n: number): string {
    if (!isFinite(n)) {
        return '—'
    }
    return `${n.toFixed(n >= 10 ? 0 : 1)}%`
}

function formatMs(n: number): string {
    if (!isFinite(n) || n === 0) {
        return '—'
    }
    if (n < 1000) {
        return `${Math.round(n)}ms`
    }
    return humanFriendlyDuration(n / 1000, { secondsPrecision: 1 })
}

// Lighten a data-viz palette hex toward white for a softer, pastel look. Stays in hex so the
// chart's gradient/gloss fill can still derive its light/dark shades (d3 rgb() can't parse oklch).
function toPastel(hex: string, amount = 0.12): string {
    const match = hex.trim().match(/^#?([0-9a-f]{6})$/i)
    if (!match) {
        return hex
    }
    const value = parseInt(match[1], 16)
    const channel = (shift: number): string => {
        const c = (value >> shift) & 255
        return Math.round(c + (255 - c) * amount)
            .toString(16)
            .padStart(2, '0')
    }
    return `#${channel(16)}${channel(8)}${channel(0)}`
}

function errorColor(theme: ChartTheme): string {
    return theme.colors[4] // red
}

function harnessSliceColor(theme: ChartTheme, category: string, fallbackIndex: number): string {
    const index = HARNESS_SLICE_COLOR_INDEX[category] ?? fallbackIndex
    return toPastel(theme.colors[index % theme.colors.length])
}

function KPITile({ tile, theme }: { tile: TileSpec; theme: ChartTheme }): JSX.Element {
    const { metric } = tile
    const hasSparkline = metric.sparkline.length > 0
    const hasComparison = metric.deltaPct !== null

    return (
        <Link
            to={tile.href}
            subtle
            className="flex flex-col rounded-lg border border-primary bg-surface-primary px-3.5 py-3 shadow-sm transition-all hover:border-secondary hover:shadow-md"
        >
            {tile.loading ? (
                <div className="flex flex-col gap-2">
                    <LemonSkeleton className="h-3 w-16" />
                    <LemonSkeleton className="h-7 w-20" />
                </div>
            ) : (
                <MetricCard
                    className="text-primary"
                    title={tile.label}
                    value={metric.value}
                    data={hasSparkline ? metric.sparkline : undefined}
                    theme={theme}
                    color={tile.color}
                    goodDirection={metric.goodDirection}
                    formatValue={tile.format}
                    subtitle={hasComparison ? `vs. ${tile.format(metric.previousValue)} prior` : undefined}
                    sparklineHeight={50}
                    sparklineClassName="mt-3 -mx-3.5 -mb-3"
                />
            )}
        </Link>
    )
}

export function MCPAnalyticsDashboardOverview(): JSX.Element {
    const {
        kpis,
        kpisLoading,
        intentClusterCount,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRawRowsLoading,
        dailyActivity,
        activityRowsLoading,
        toolDailySeries,
        toolDailyRowsLoading,
        toolRows,
        toolRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)
    const { isDarkModeOn } = useValues(themeLogic)
    const { timezone } = useValues(teamLogic)

    const theme = useMemo<ChartTheme>(() => buildTheme(), [isDarkModeOn])

    const tiles: TileSpec[] = [
        {
            label: 'Sessions',
            metric: kpis.sessions,
            href: urls.mcpAnalyticsSessions(),
            format: formatNumber,
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Tool calls',
            metric: kpis.toolCalls,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatNumber,
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Error rate',
            metric: kpis.errorRatePct,
            href: urls.mcpAnalyticsSessions(),
            format: formatPercent,
            color: theme.colors[4], // --data-color-5 (red)
            loading: kpisLoading,
        },
        {
            label: 'p95 latency',
            metric: kpis.p95LatencyMs,
            href: urls.mcpAnalyticsToolQuality(),
            format: formatMs,
            color: theme.colors[0], // --data-color-1 (blue)
            loading: kpisLoading,
        },
        {
            label: 'Intent clusters',
            metric: intentClusterCount,
            href: urls.mcpAnalyticsIntentClustering(),
            format: formatNumber,
            color: theme.colors[6], // --data-color-7 (green)
            loading: false,
        },
    ]

    return (
        <div className="flex flex-col gap-10">
            <section>
                <h2 className="mb-4 text-xl font-semibold text-primary">Previous week's key metrics</h2>
                <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                    {tiles.map((tile) => (
                        <KPITile key={tile.label} tile={tile} theme={theme} />
                    ))}
                </div>
            </section>
            <section>
                <h2 className="mb-4 text-xl font-semibold text-primary">Last month's usage</h2>
                <div className="flex flex-col gap-[22px]">
                    <div className="grid grid-cols-1 gap-[22px] lg:grid-cols-3">
                        <div className="flex lg:col-span-2">
                            <ActivityChart
                                daily={dailyActivity}
                                loading={activityRowsLoading}
                                theme={theme}
                                timezone={timezone}
                            />
                        </div>
                        <HarnessDonut rows={harnessRows} loading={harnessRawRowsLoading} theme={theme} />
                    </div>
                    <div className="grid grid-cols-1 gap-[22px] lg:grid-cols-2">
                        <ToolErrorRateChart rows={toolRows} loading={toolRowsLoading} theme={theme} />
                        <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
                    </div>
                    <ToolUsageChart
                        data={toolDailySeries}
                        loading={toolDailyRowsLoading}
                        theme={theme}
                        timezone={timezone}
                    />
                </div>
            </section>
        </div>
    )
}

function Card({
    children,
    className,
    title,
}: {
    children: React.ReactNode
    className?: string
    title?: string
}): JSX.Element {
    return (
        <div className={cn('rounded-lg border border-primary bg-surface-primary px-3.5 py-3', className)}>
            {title ? <h3 className="mb-3 text-sm font-medium text-primary">{title}</h3> : null}
            {children}
        </div>
    )
}

type ErrorBucket = 'green' | 'amber' | 'red'

function errorBucket(pct: number): ErrorBucket {
    if (pct < 1) {
        return 'green'
    }
    if (pct <= 5) {
        return 'amber'
    }
    return 'red'
}

function ChartTooltip({ title, rows }: { title: string; rows: [string, string][] }): JSX.Element {
    return (
        <div className="rounded-md border border-primary bg-surface-primary px-2.5 py-2 text-xs shadow-md">
            <div className="mb-1 font-medium text-primary">{title}</div>
            {rows.map(([label, value]) => (
                <div key={label} className="flex justify-between gap-4 text-secondary">
                    <span>{label}</span>
                    <span className="font-mono text-primary">{value}</span>
                </div>
            ))}
        </div>
    )
}

// Stacked vertical bars: daily tool-call volume, one stacked segment per tool.
function ToolUsageChart({
    data,
    loading,
    theme,
    timezone,
}: {
    data: ToolDailySeries
    loading: boolean
    theme: ChartTheme
    timezone: string
}): JSX.Element {
    const series = useMemo<Series[]>(
        () =>
            data.tools.map((t, i) => ({
                key: t.tool,
                label: t.tool,
                // Desaturate the palette a touch — fully-saturated stacked colors trigger
                // chromostereopsis, where segments appear to differ in width even though they don't.
                color: toPastel(theme.colors[i % theme.colors.length], 0.15),
                data: t.data,
            })),
        [data, theme]
    )
    const config = useMemo<TimeSeriesBarChartConfig>(
        () => ({
            barLayout: 'stacked',
            barCornerRadius: 2,
            yAxis: { showGrid: false },
            showAxisLines: true,
            xAxis: { interval: 'day', timezone },
            tooltip: { placement: 'cursor' },
        }),
        [timezone]
    )

    return (
        <Card title="Daily breakdown of tool calls">
            {loading && data.labels.length === 0 ? (
                <LemonSkeleton className="h-[260px] w-full" />
            ) : data.labels.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>
            ) : (
                <div className="flex h-[260px] flex-col">
                    <TimeSeriesBarChart series={series} labels={data.labels} config={config} theme={theme} />
                </div>
            )}
        </Card>
    )
}

// A "nice" upper bound for the error-rate track: a bit above the worst tool's rate, rounded up to a
// clean 10 — so the track ends just past the data (e.g. a 30% max gives a 50% track) instead of an
// always-empty-looking 100%.
function niceErrorAxisMax(maxRate: number): number {
    return Math.min(100, Math.max(10, Math.ceil((maxRate * 1.4) / 10) * 10))
}

// Horizontal bars of error rate per tool, sorted worst-first.
function ToolErrorRateChart({
    rows,
    loading,
    theme,
}: {
    rows: ToolRow[]
    loading: boolean
    theme: ChartTheme
}): JSX.Element {
    const sorted = useMemo(() => [...rows].sort((a, b) => b.error_rate_pct - a.error_rate_pct), [rows])
    const labels = useMemo(() => sorted.map((r) => r.tool), [sorted])
    const series = useMemo<Series[]>(
        () => [
            {
                key: 'errorRate',
                label: 'Error rate',
                color: theme.colors[4],
                data: sorted.map((r) => r.error_rate_pct),
            },
        ],
        [sorted, theme]
    )
    const config = useMemo<BarChartConfig>(() => {
        const axisMax = niceErrorAxisMax(sorted[0]?.error_rate_pct ?? 0)
        return {
            axisOrientation: 'horizontal',
            barLayout: 'grouped',
            showGrid: false,
            showAxisLines: false,
            tooltip: { placement: 'cursor' },
            margins: { top: 4, right: 20, bottom: 22 },
            bars: { cornerRadius: 3, minBandSize: 30, track: { hover: false }, valueDomain: [0, axisMax] },
        }
    }, [sorted])
    const renderTooltip = (ctx: TooltipContext): JSX.Element | null => {
        const row = sorted.find((r) => r.tool === ctx.label)
        if (!row) {
            return null
        }
        return (
            <ChartTooltip
                title={row.tool}
                rows={[
                    ['Error rate', formatPercent(row.error_rate_pct)],
                    ['Errors', String(row.errors)],
                    ['Calls', String(row.total_calls)],
                ]}
            />
        )
    }

    return (
        <Card title="Tools with the highest error rate">
            {loading && rows.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-7 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>
            ) : (
                <div className="flex flex-col">
                    <BarChart series={series} labels={labels} config={config} theme={theme} tooltip={renderTooltip}>
                        <ValueLabels valueFormatter={(value) => formatPercent(value)} offset={6} />
                    </BarChart>
                </div>
            )}
        </Card>
    )
}

const HARNESS_DONUT_CONFIG: PieChartConfig = {
    innerRadiusRatio: 0.6,
    // Built-in text labels are off — a custom overlay (HarnessSliceLabels) draws logo pills instead.
    showLabelOnSlice: false,
    showValueOnSlice: false,
}

// Overlay that drops a HarnessPill (logo + name) onto the middle of each slice's arc. Rendered as a
// PieChart child so it can read the slice geometry from the radial layout context.
function HarnessSliceLabels(): JSX.Element | null {
    const { layout } = useRadialLayout()
    const midRadius = layout.innerRadius + (layout.outerRadius - layout.innerRadius) / 2
    return (
        <>
            {layout.slices.map((slice) => {
                if (slice.fraction < 0.05) {
                    return null
                }
                const x = layout.cx + Math.sin(slice.centroidAngle) * midRadius
                const y = layout.cy - Math.cos(slice.centroidAngle) * midRadius
                const category = slice.series.label
                const logo = HARNESS_LOGOS[category]
                return (
                    <div
                        key={slice.series.key}
                        className="pointer-events-none absolute"
                        style={{ left: x, top: y, transform: 'translate(-50%, -50%)' }}
                    >
                        {logo ? (
                            <img
                                src={logo}
                                alt={category}
                                title={category}
                                className="h-7 w-7 object-contain"
                                style={{ filter: 'drop-shadow(0 1px 2px rgba(0, 0, 0, 0.45))' }}
                            />
                        ) : (
                            <HarnessPill category={category} />
                        )}
                    </div>
                )
            })}
        </>
    )
}

// Donut of call share by harness, with a logo legend alongside.
function HarnessDonut({
    rows,
    loading,
    theme,
}: {
    rows: HarnessRow[]
    loading: boolean
    theme: ChartTheme
}): JSX.Element {
    const totalCalls = rows.reduce((acc, r) => acc + r.total_calls, 0)
    const series = useMemo<Series<HarnessRow>[]>(
        () =>
            rows.map((r, i) => ({
                key: r.category,
                label: r.category,
                color: harnessSliceColor(theme, r.category, i),
                data: [r.total_calls],
                meta: r,
            })),
        [rows, theme]
    )
    const renderTooltip = (ctx: TooltipContext<HarnessRow>): JSX.Element | null => {
        const entry = ctx.seriesData[0]
        const row = entry?.series.meta
        if (!row) {
            return null
        }
        const share = entry.fraction !== undefined ? entry.fraction * 100 : 0
        return (
            <ChartTooltip
                title={row.category}
                rows={[
                    ['Calls', String(row.total_calls)],
                    ['Share', formatPercent(share)],
                    ['Sessions', String(row.sessions)],
                    ['Error rate', formatPercent(row.error_rate_pct)],
                ]}
            />
        )
    }

    if (loading && rows.length === 0) {
        return (
            <Card className="flex flex-1 flex-col" title="Share of calls by harness">
                <div className="flex min-h-[300px] flex-1 items-center justify-center">
                    <LemonSkeleton className="h-[180px] w-[180px] rounded-full" />
                </div>
            </Card>
        )
    }
    if (rows.length === 0) {
        return (
            <Card className="flex flex-1 flex-col" title="Breakdown of tool calls by harness">
                <div className="flex min-h-[300px] flex-1 items-center justify-center text-[12px] text-secondary">
                    No harness data yet.
                </div>
            </Card>
        )
    }

    return (
        <Card className="flex flex-1 flex-col" title="Share of calls by harness">
            <div className="flex min-h-[300px] flex-1 flex-col">
                <PieChart<HarnessRow>
                    series={series}
                    theme={theme}
                    config={HARNESS_DONUT_CONFIG}
                    tooltip={renderTooltip}
                    centerLabel={
                        <div className="text-center">
                            <div className="text-3xl font-semibold text-primary">{formatNumber(totalCalls)}</div>
                            <div className="text-xs text-secondary">calls</div>
                        </div>
                    }
                >
                    <HarnessSliceLabels />
                </PieChart>
            </div>
        </Card>
    )
}

// Daily tool-call volume (busy) and errors (erroring) as two lines, over the activity window.
function ActivityChart({
    daily,
    loading,
    theme,
    timezone,
}: {
    daily: DailyActivity
    loading: boolean
    theme: ChartTheme
    timezone: string
}): JSX.Element {
    const series = useMemo<Series[]>(() => {
        const totals = daily.successes.map((s, i) => s + (daily.errors[i] ?? 0))
        return [
            { key: 'calls', label: 'Tool calls', color: theme.colors[0], data: totals },
            { key: 'errors', label: 'Errors', color: errorColor(theme), data: daily.errors },
        ]
    }, [daily, theme])
    // quill's built-in date tick formatter only kicks in when both interval and timezone are set.
    const config = useMemo<TimeSeriesLineChartConfig>(
        () => ({
            yAxis: { showGrid: false },
            showAxisLines: true,
            xAxis: { interval: 'day', timezone },
            showCrosshair: true,
            tooltip: { placement: 'cursor' },
        }),
        [timezone]
    )

    return (
        <Card className="flex flex-1 flex-col" title="Daily tool calls and errors">
            {loading && daily.labels.length === 0 ? (
                <LemonSkeleton className="min-h-[300px] flex-1" />
            ) : daily.labels.length === 0 ? (
                <div className="flex flex-1 items-center justify-center py-6 text-center text-[12px] text-secondary">
                    No activity yet.
                </div>
            ) : (
                <div className="flex min-h-[300px] flex-1 flex-col">
                    <TimeSeriesLineChart series={series} labels={daily.labels} config={config} theme={theme} />
                </div>
            )}
        </Card>
    )
}

function truncateSessionId(id: string): string {
    if (id.length <= 12) {
        return id
    }
    return `${id.slice(0, 4)}…${id.slice(-4)}`
}

function formatDuration(seconds: number): string {
    if (!seconds || !isFinite(seconds)) {
        return '—'
    }
    if (seconds < 60) {
        return `${seconds}s`
    }
    return humanFriendlyDuration(seconds, { secondsPrecision: 0 })
}

function StatusPill({ errorRatePct }: { errorRatePct: number }): JSX.Element {
    if (errorRatePct === 0) {
        return <Badge variant="success">Healthy</Badge>
    }
    const bucket = errorBucket(errorRatePct)
    const variant = bucket === 'red' ? 'destructive' : bucket === 'amber' ? 'warning' : 'success'
    return <Badge variant={variant}>{formatPercent(errorRatePct)} errors</Badge>
}

function NotableSessionsTable({ sessions, loading }: { sessions: NotableSession[]; loading: boolean }): JSX.Element {
    return (
        <div className="flex h-full flex-col overflow-hidden rounded-lg border border-primary bg-surface-primary">
            <h3 className="mb-0 border-b border-primary px-3.5 py-3 text-sm font-medium text-primary">
                Sessions flagged for review
            </h3>
            <Table fullWidth>
                <TableHeader>
                    <TableRow>
                        <TableHead>Session</TableHead>
                        <TableHead align="right">Calls</TableHead>
                        <TableHead align="right">Duration</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead expand>Why notable</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {loading && sessions.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={5}>
                                <div className="space-y-2 py-1">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                                    ))}
                                </div>
                            </TableCell>
                        </TableRow>
                    ) : sessions.length === 0 ? (
                        <TableRow>
                            <TableCell colSpan={5} align="center" className="py-6 text-secondary">
                                No notable sessions in the last 30 days.
                            </TableCell>
                        </TableRow>
                    ) : (
                        sessions.map((entry) => (
                            <TableRow key={entry.session.session_id}>
                                <TableCell className="whitespace-nowrap">
                                    <Link
                                        to={urls.mcpAnalyticsSessions()}
                                        className="font-mono"
                                        title={entry.session.session_id}
                                    >
                                        {truncateSessionId(entry.session.session_id)}
                                    </Link>
                                </TableCell>
                                <TableCell align="right">{entry.session.tool_calls}</TableCell>
                                <TableCell align="right">{formatDuration(entry.session.duration_seconds)}</TableCell>
                                <TableCell>
                                    <StatusPill errorRatePct={entry.session.error_rate_pct} />
                                </TableCell>
                                <TableCell expand className="text-primary" title={entry.label}>
                                    {entry.label}
                                </TableCell>
                            </TableRow>
                        ))
                    )}
                </TableBody>
            </Table>
            {sessions.length > 0 && (
                <div className="mt-auto flex justify-end border-t border-primary px-3.5 py-2">
                    <Link to={urls.mcpAnalyticsSessions()} className="text-[10px]">
                        Open all flagged sessions in Sessions tab ↗
                    </Link>
                </div>
            )}
        </div>
    )
}
