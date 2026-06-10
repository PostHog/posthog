import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconBolt } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'
import { type ChartTheme, MetricCard } from '@posthog/quill-charts'

import { buildTheme } from 'lib/charts/utils/theme'
import { humanFriendlyDuration, humanFriendlyLargeNumber } from 'lib/utils'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import claudeLogo from './harness-logos/claude.svg'
import cursorLogo from './harness-logos/cursor.svg'
import openaiLogo from './harness-logos/openai.svg'
import vscodeLogo from './harness-logos/vscode.svg'
import { HarnessRow, KPIMetric, NotableSession, ToolRow, mcpDashboardOverviewLogic } from './mcpDashboardOverviewLogic'

const HARNESS_LOGOS: Record<string, string> = {
    'Claude Code': claudeLogo,
    'Claude.ai': claudeLogo,
    'OpenAI Codex': openaiLogo,
    Cursor: cursorLogo,
    'VS Code': vscodeLogo,
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
        topToolRows,
        toolRowsLoading,
        toolRowsTotal,
        notableSessions,
        sessionRowsLoading,
        harnessRows,
        harnessRawRowsLoading,
    } = useValues(mcpDashboardOverviewLogic)
    const { isDarkModeOn } = useValues(themeLogic)

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
        <div className="flex flex-col gap-[22px]">
            <BrandingStrip />
            <Block kicker="Health" question="Is the MCP healthy right now?">
                <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                    {tiles.map((tile) => (
                        <KPITile key={tile.label} tile={tile} theme={theme} />
                    ))}
                </div>
            </Block>
            <Block kicker="Tool quality" question="Which tools are the weak links?">
                <ToolReliabilityMatrix rows={topToolRows} loading={toolRowsLoading} totalTools={toolRowsTotal} />
            </Block>
            <Block kicker="Surface" question="Which harnesses are calling the MCP?">
                <HarnessBreakdown rows={harnessRows} loading={harnessRawRowsLoading} />
            </Block>
            <Block kicker="Triage" question="Which sessions should I look at?">
                <NotableSessionsTable sessions={notableSessions} loading={sessionRowsLoading} />
            </Block>
        </div>
    )
}

function BrandingStrip(): JSX.Element {
    return (
        <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
                <span className="flex h-[22px] w-[22px] items-center justify-center rounded bg-warning text-white">
                    <IconBolt className="h-3 w-3" />
                </span>
                <span className="text-[13px] font-medium">PostHog for Agents</span>
                <LemonTag type="completion" size="small">
                    Alpha
                </LemonTag>
            </div>
            <span className="text-[11px] text-tertiary">Last 7 days</span>
        </div>
    )
}

function Block({
    kicker,
    question,
    children,
}: {
    kicker: string
    question: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <section className="flex flex-col">
            <div className="text-[11px] text-secondary mb-1">{kicker}</div>
            <h1 className="text-sm font-medium mb-3">{question}</h1>
            {children}
        </section>
    )
}

function Card({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="rounded-lg border border-primary bg-surface-primary px-3.5 py-3">{children}</div>
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

const ERROR_PILL_CLASS: Record<ErrorBucket, string> = {
    green: 'text-success bg-fill-success-highlight',
    amber: 'text-warning bg-fill-warning-highlight',
    red: 'text-error bg-fill-error-highlight',
}

function ErrorRatePill({ pct }: { pct: number }): JSX.Element {
    const bucket = errorBucket(pct)
    return (
        <span
            className={`inline-flex h-[14px] items-center justify-center rounded-[3px] px-1.5 text-[10px] font-medium ${ERROR_PILL_CLASS[bucket]}`}
        >
            {pct.toFixed(pct >= 10 ? 0 : 1)}%
        </span>
    )
}

const VOLUME_COLOR = 'var(--data-color-1)'
const ERROR_COLOR = 'var(--data-color-5)'

function VolumeBar({ totalPct, errorPct, title }: { totalPct: number; errorPct: number; title: string }): JSX.Element {
    const errorStartPct = (Math.max(totalPct - errorPct, 0) / (totalPct || 1)) * 100
    return (
        <div className="relative h-[14px] overflow-hidden rounded-[3px] bg-surface-secondary" title={title}>
            <div
                className="h-full opacity-40"
                style={{
                    width: `${totalPct}%`,
                    background: `linear-gradient(to right, ${VOLUME_COLOR} ${errorStartPct}%, ${ERROR_COLOR} ${errorStartPct}%)`,
                }}
            />
        </div>
    )
}

function ToolRowItem({ row, maxVolume, isLast }: { row: ToolRow; maxVolume: number; isLast: boolean }): JSX.Element {
    const callsPct = maxVolume ? (row.total_calls / maxVolume) * 100 : 0
    const errorsPct = maxVolume ? (row.errors / maxVolume) * 100 : 0
    const nameClass = row.error_rate_pct > 5 ? 'text-error' : 'text-primary'
    return (
        <div
            className="grid items-center gap-2.5 py-1.5"
            style={{
                gridTemplateColumns: '140px 1fr 60px 56px',
                borderBottom: isLast ? 'none' : '0.5px solid var(--color-border-tertiary)',
            }}
        >
            <Link
                to={urls.mcpAnalyticsTool(row.tool)}
                className={`truncate font-mono text-xs ${nameClass}`}
                title={row.tool}
            >
                {row.tool}
            </Link>
            <VolumeBar
                totalPct={callsPct}
                errorPct={errorsPct}
                title={`${row.total_calls} calls · ${row.errors} errors`}
            />
            <ErrorRatePill pct={row.error_rate_pct} />
            <span className="text-right font-mono text-xs text-primary">
                {row.p95_duration_ms ? `${Math.round(row.p95_duration_ms)}ms` : '—'}
            </span>
        </div>
    )
}

function ToolReliabilityMatrix({
    rows,
    loading,
    totalTools,
}: {
    rows: ToolRow[]
    loading: boolean
    totalTools: number
}): JSX.Element {
    const maxVolume = rows.length ? Math.max(...rows.map((r) => r.total_calls)) : 0

    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: '140px 1fr 60px 56px',
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Tool</span>
                <span>
                    <span style={{ color: VOLUME_COLOR }}>Calls</span>
                    <span className="mx-1">·</span>
                    <span style={{ color: ERROR_COLOR }}>errors</span>
                </span>
                <span>Err</span>
                <span className="text-right">p95</span>
            </div>
            {loading && rows.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No tool calls yet.</div>
            ) : (
                rows.map((row, i) => (
                    <ToolRowItem key={row.tool} row={row} maxVolume={maxVolume} isLast={i === rows.length - 1} />
                ))
            )}
            {rows.length > 0 && (
                <div className="mt-1.5 flex justify-end">
                    <Link to={urls.mcpAnalyticsToolQuality()} className="text-[10px]">
                        View all {totalTools} tools ↗
                    </Link>
                </div>
            )}
        </Card>
    )
}

const HARNESS_GRID_TEMPLATE = '160px 1fr 56px 56px'

function HarnessBreakdown({ rows, loading }: { rows: HarnessRow[]; loading: boolean }): JSX.Element {
    const maxCalls = rows.length ? Math.max(...rows.map((r) => r.total_calls)) : 0
    const totalCalls = rows.reduce((acc, r) => acc + r.total_calls, 0)

    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: HARNESS_GRID_TEMPLATE,
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Harness</span>
                <span>
                    <span style={{ color: VOLUME_COLOR }}>Calls</span>
                    <span className="mx-1">·</span>
                    <span style={{ color: ERROR_COLOR }}>errors</span>
                </span>
                <span>Err</span>
                <span className="text-right">Share</span>
            </div>
            {loading && rows.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 5 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : rows.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">No harness data yet.</div>
            ) : (
                rows.map((row, i) => {
                    const callsPct = maxCalls ? (row.total_calls / maxCalls) * 100 : 0
                    const errorsPct = maxCalls ? (row.errors / maxCalls) * 100 : 0
                    const share = totalCalls ? (row.total_calls / totalCalls) * 100 : 0
                    const tooltip = row.raw_clients.slice(0, 8).join(', ')
                    return (
                        <div
                            key={row.category}
                            className="grid items-center gap-2.5 py-1.5"
                            style={{
                                gridTemplateColumns: HARNESS_GRID_TEMPLATE,
                                borderBottom:
                                    i === rows.length - 1 ? 'none' : '0.5px solid var(--color-border-tertiary)',
                            }}
                        >
                            <HarnessPill category={row.category} title={tooltip} />
                            <VolumeBar
                                totalPct={callsPct}
                                errorPct={errorsPct}
                                title={`${row.total_calls} calls · ${row.errors} errors · ${row.sessions} sessions`}
                            />
                            <ErrorRatePill pct={row.error_rate_pct} />
                            <span className="text-right font-mono text-xs text-primary">
                                {share.toFixed(share >= 10 ? 0 : 1)}%
                            </span>
                        </div>
                    )
                })
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
    if (errorRatePct >= 100) {
        return (
            <span className="inline-flex h-[14px] items-center rounded-[3px] bg-fill-error-highlight px-1.5 text-[10px] font-medium text-error">
                100% err
            </span>
        )
    }
    if (errorRatePct > 0) {
        const bucket = errorBucket(errorRatePct)
        return (
            <span
                className={`inline-flex h-[14px] items-center rounded-[3px] px-1.5 text-[10px] font-medium ${ERROR_PILL_CLASS[bucket]}`}
            >
                {errorRatePct.toFixed(errorRatePct >= 10 ? 0 : 1)}% err
            </span>
        )
    }
    return (
        <span className="inline-flex h-[14px] items-center rounded-[3px] bg-fill-success-highlight px-1.5 text-[10px] font-medium text-success">
            Success
        </span>
    )
}

const NOTABLE_GRID_TEMPLATE = '22% 12% 14% 18% 1fr'

function NotableSessionsTable({ sessions, loading }: { sessions: NotableSession[]; loading: boolean }): JSX.Element {
    return (
        <Card>
            <div
                className="grid items-center gap-2.5 pb-1.5 text-[11px] text-secondary"
                style={{
                    gridTemplateColumns: NOTABLE_GRID_TEMPLATE,
                    borderBottom: '0.5px solid var(--color-border-secondary)',
                }}
            >
                <span>Session</span>
                <span>Calls</span>
                <span>Duration</span>
                <span>Status</span>
                <span>Why notable</span>
            </div>
            {loading && sessions.length === 0 ? (
                <div className="space-y-2 py-3">
                    {Array.from({ length: 4 }).map((_, i) => (
                        <LemonSkeleton key={i} className="h-3.5 w-full" />
                    ))}
                </div>
            ) : sessions.length === 0 ? (
                <div className="py-6 text-center text-[12px] text-secondary">
                    No notable sessions in the last 7 days.
                </div>
            ) : (
                sessions.map((entry, i) => (
                    <div
                        key={entry.session.session_id}
                        className="grid items-center gap-2.5 py-1.5"
                        style={{
                            gridTemplateColumns: NOTABLE_GRID_TEMPLATE,
                            borderBottom:
                                i === sessions.length - 1 ? 'none' : '0.5px solid var(--color-border-tertiary)',
                        }}
                    >
                        <Link
                            to={urls.mcpAnalyticsSessions()}
                            className="truncate font-mono text-[11px]"
                            title={entry.session.session_id}
                        >
                            {truncateSessionId(entry.session.session_id)}
                        </Link>
                        <span className="text-[11px]">{entry.session.tool_calls}</span>
                        <span className="text-[11px]">{formatDuration(entry.session.duration_seconds)}</span>
                        <StatusPill errorRatePct={entry.session.error_rate_pct} />
                        <span className="truncate text-[11px] text-primary" title={entry.label}>
                            {entry.label}
                        </span>
                    </div>
                ))
            )}
            {sessions.length > 0 && (
                <div className="mt-1.5 flex justify-end">
                    <Link to={urls.mcpAnalyticsSessions()} className="text-[10px]">
                        Open all flagged sessions in Sessions tab ↗
                    </Link>
                </div>
            )}
        </Card>
    )
}
